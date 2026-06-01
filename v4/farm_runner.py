from __future__ import annotations

"""Vision-guided EventLab farm loop.

Drop-in replacement for the V1 SmartRunner farm loop, but driven by the
aspect-robust V3 hybrid recognizer (YOLO + V2 rules + OCR) instead of the
fixed-fraction ForzaScreenDetector. This is what lets the farm phase survive
different resolutions / aspect ratios.

It sends only normal virtual Xbox controller input (via the shared pad
provider). It does not inject, hook, fake focus, or modify game files. Full
throttle is applied with ``pad.apply`` and the virtual pad holds that state
between cycles, so the car keeps driving smoothly even while the recognizer
re-reads the screen.
"""

import ctypes
import logging
import threading
import time
from ctypes import wintypes

import focus
from screen_detector import (
    STATE_CONFIRM_RESTART,
    STATE_CONTROLLER_DISCONNECTED,
    STATE_PAUSE_MENU,
    STATE_POST_RACE_NEXT,
    STATE_PRESTART,
    STATE_PRESTART_WRONG_SELECTION,
    STATE_RACING,
    STATE_RESULTS,
)
from v4.decision import decide_farm_loop, normalize_button
from v4.recognizer import V4Recognizer


# Screens that mean "we have left the active race" -- used to end the loop
# cleanly after a graceful exit.
_LEFT_RACE_SCREENS = {
    "post_race_next",
    "free_roam_hud",
    "idle_showcase",
    "race_pause_menu",
    "pause_menu",
}


class VisionFarmRunner:
    """Run the EventLab farm loop from V3 hybrid recognition only.

    Mirrors the SmartRunner interface (start/stop/is_running/
    request_graceful_exit/exit_reason) so V4 can swap it in for the farm phase.
    """

    def __init__(
        self,
        title: str = "Forza",
        recognizer: V4Recognizer | None = None,
        on_log=None,
        logger=None,
        pad_provider=None,
        min_confidence: float = 0.42,
        stall_seconds: float = 120.0,
        race_poll: float = 1.2,
    ):
        self.title = title
        self.on_log = on_log or (lambda message: None)
        self.logger = logger or logging.getLogger("forza6helper.v4.farm")
        self.pad_provider = pad_provider
        self.recognizer = recognizer or V4Recognizer(
            title=title, min_confidence=min_confidence, logger=self.logger
        )
        self.stall_seconds = float(stall_seconds)
        self.race_poll = float(race_poll)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._graceful = threading.Event()
        self.exit_reason: str | None = None
        self.laps = 0
        self.race_hud_seen = 0

    # -- lifecycle ---------------------------------------------------------
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        startup_delay: float = 0.0,
        total_seconds: float | None = None,
        auto_focus: bool = False,
        require_foreground: bool = True,
    ) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._graceful.clear()
        self.exit_reason = None
        self._thread = threading.Thread(
            target=self._run,
            args=(startup_delay, total_seconds, auto_focus, require_foreground),
            name="vision-farm-runner",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self.exit_reason = self.exit_reason or "manual_stop"
        self._stop.set()

    def request_graceful_exit(self) -> None:
        if not self._graceful.is_set():
            self.on_log("视觉刷图：收到平滑退出请求，跑完当前比赛在结算页按 A 退出。")
        self._graceful.set()

    # -- helpers -----------------------------------------------------------
    def _sleep(self, seconds: float) -> bool:
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._stop.is_set():
                return False
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))
        return not self._stop.is_set()

    def _activate(self) -> None:
        hwnd = focus.find_window(self.title)
        if not hwnd or not focus.user32:
            return
        try:
            focus.user32.ShowWindow(hwnd, focus.SW_RESTORE)
            focus.user32.BringWindowToTop(hwnd)
            focus.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _click_to_focus(self) -> bool:
        """Real title-bar click to focus Forza. SetForegroundWindow from a
        background process is refused by Windows; a synthetic click is honored."""
        hwnd = focus.find_window(self.title)
        if not hwnd or not focus.user32:
            return False
        try:
            rect = wintypes.RECT()
            if not focus.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return False
            x = int(rect.left + min(160, max(60, (rect.right - rect.left) * 0.10)))
            y = int(rect.top + 16)
            focus.user32.SetCursorPos(x, y)
            time.sleep(0.05)
            focus.user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.05)
            focus.user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.2)
            return True
        except Exception:
            return False

    def _press_enter(self) -> None:
        try:
            user32 = ctypes.windll.user32
            user32.keybd_event(0x0D, 0, 0, 0)
            time.sleep(0.12)
            user32.keybd_event(0x0D, 0, 0x0002, 0)
        except Exception:
            pass

    def _race_poll_interval(self, race_started: float | None) -> float:
        if race_started is None:
            return min(0.6, self.race_poll)
        # Slightly tighter polling at the very start (countdown), then relax.
        return self.race_poll if (time.monotonic() - race_started) > 4.0 else min(0.6, self.race_poll)

    @staticmethod
    def _settle_for(name: str) -> float:
        if name in ("farm_start_race", "farm_confirm_restart", "farm_confirm_modal"):
            return 1.15
        if name in ("farm_dismiss_controller", "farm_restart_results", "farm_graceful_exit_results"):
            return 0.9
        return 0.55

    def _capture_farm_snapshot(self):
        snapshot = self.recognizer.capture(full_ocr=False, region_ocr=True)
        return self._apply_smart_farm_hint(snapshot)

    def _apply_smart_farm_hint(self, snapshot):
        smart_state = str(getattr(snapshot, "smart_state", "") or "")
        smart_conf = float(getattr(snapshot, "smart_confidence", 0.0) or 0.0)
        if smart_conf < 0.60:
            return snapshot

        hints = {
            STATE_PRESTART: ("race_menu", "STARTEVENT", 0.82),
            STATE_PRESTART_WRONG_SELECTION: ("race_menu", "not_start_focus", 0.66),
            STATE_RACING: ("race_hud", "", 0.84),
            STATE_RESULTS: ("race_result", "", 0.84),
            STATE_CONFIRM_RESTART: ("modal_warning", "restart_event", 0.82),
            STATE_CONTROLLER_DISCONNECTED: ("controller_disconnected", "", 0.82),
            STATE_PAUSE_MENU: ("pause_menu", "", 0.70),
            STATE_POST_RACE_NEXT: ("post_race_next", "", 0.78),
        }
        hint = hints.get(smart_state)
        if not hint:
            return snapshot

        v3 = snapshot.v3
        current_screen = str(getattr(v3, "screen", "") or "unknown")
        current_conf = float(getattr(v3, "confidence", 0.0) or 0.0)
        # Free roam is NEVER a race. Trust V3's free_roam_hud over V1's smart so the
        # farm never holds throttle in the open world -- the festival start line
        # mis-reads as RACING for V1's fixed-fraction detector, and without this the
        # RACING hint would force race_hud -> race_drive_throttle while parked.
        if current_screen == "free_roam_hud":
            return snapshot
        hinted_screen, hinted_selected, hinted_conf = hint
        override_screens = {
            "unknown",
            "idle_showcase",
            "loading_transition",
            "race_menu",
            "pause_story",
            "pause_menu",
            "modal_warning",
        }
        if current_screen not in override_screens and current_conf >= 0.80:
            return snapshot

        # Farm loop safety prefers the old color/layout detector for race HUD,
        # results, and restart modal. It is much faster than full OCR and helps
        # prevent YOLO's occasional race_menu/race_hud confusion.
        v3.screen = hinted_screen
        v3.confidence = max(current_conf, min(0.95, smart_conf, hinted_conf))
        if hinted_selected and not str(getattr(v3, "selected_item", "") or ""):
            v3.selected_item = hinted_selected
        reasons = getattr(v3, "reasons", None)
        if isinstance(reasons, list):
            reasons.append(f"V4 farm smart hint {smart_state}->{hinted_screen} conf={smart_conf:.2f}")
        return snapshot

    # -- main loop ---------------------------------------------------------
    def _run(self, startup_delay, total_seconds, auto_focus, require_foreground) -> None:
        try:
            pad = self.pad_provider()
        except Exception as exc:
            self.logger.exception("vision farm pad init failed")
            self.on_log(f"无法启动虚拟手柄：{exc}")
            return

        self.exit_reason = None
        self.laps = 0
        self.race_hud_seen = 0
        if startup_delay > 0 and not self._sleep(startup_delay):
            pad.neutral()
            return

        started = time.monotonic()
        in_race = False
        race_started: float | None = None
        unknown_throttle_since: float | None = None
        launching = False
        launch_since = 0.0
        controller_strikes = 0
        last_screen: str | None = None
        last_token: str | None = None
        last_progress = time.monotonic()
        self.on_log(
            "视觉刷图已启动：race_menu 按 A 开赛、race_hud 保持油门、结算页按 X 重开、"
            "暂停/赛后按 B 返回；全部基于 V3 模型/规则识别，按一步重新识别验证。"
        )

        try:
            while not self._stop.is_set():
                if total_seconds is not None and time.monotonic() - started >= total_seconds:
                    if not self._graceful.is_set():
                        self._graceful.set()
                        self.on_log("视觉刷图：总时长已到，进入平滑退出，跑完当前比赛后在结算页按 A 退出。")

                if require_foreground and not focus.is_foreground(self.title):
                    pad.neutral()
                    in_race = False
                    race_started = None
                    if auto_focus:
                        self._activate()
                    if not self._sleep(0.8):
                        break
                    continue

                try:
                    snapshot = self._capture_farm_snapshot()
                except Exception as exc:
                    self.logger.warning("vision farm capture failed: %s", exc)
                    if not self._sleep(0.8):
                        break
                    continue

                v3 = snapshot.v3
                screen = str(getattr(v3, "screen", "") or "unknown")
                token = f"{screen}|{getattr(v3, 'selected_item', '')}"
                if token != last_token:
                    last_token = token
                    last_progress = time.monotonic()
                if screen != last_screen:
                    self.on_log(f"视觉刷图识别：{screen}")
                    last_screen = screen

                if time.monotonic() - last_progress > self.stall_seconds:
                    self.exit_reason = self.exit_reason or "stall"
                    self.on_log(
                        f"视觉刷图：{self.stall_seconds:.0f} 秒没有语义进展，停止并把控制权交回上层。"
                    )
                    break

                decision = decide_farm_loop(v3, graceful_exit=self._graceful.is_set())
                name = decision.name
                if name != "farm_dismiss_controller":
                    controller_strikes = 0

                # Controller-disconnected recovery: try the virtual pad's A
                # first (works once the pad is warm). If it persists, the game
                # has fallen back to keyboard input (the modal shows "Enter 确定"),
                # so click-to-focus + press Enter. Focus loss (e.g. other window
                # activity) drops the virtual pad; this recovers without stalling.
                if name == "farm_dismiss_controller":
                    in_race = False
                    race_started = None
                    unknown_throttle_since = None
                    launching = False
                    pad.neutral()
                    controller_strikes += 1
                    if controller_strikes <= 2:
                        self.on_log(f"视觉刷图：控制器未连接，虚拟手柄按 A 重连(第 {controller_strikes} 次)。")
                        pad.tap("a", hold=0.15)
                    else:
                        self.on_log("视觉刷图：控制器弹窗未消(疑似已切键盘模式)，点标题栏聚焦 + 键盘 Enter 兜底。")
                        self._click_to_focus()
                        self._press_enter()
                    if not self._sleep(1.2):
                        break
                    continue

                # Launch window: right after pressing A to start a race, the
                # countdown / loading / start-line frames can mis-read as
                # race_menu/idle/loading. Hold full throttle through that window
                # (so the car actually launches) until the HUD confirms. We must
                # NEVER press DpadUp here -- in-race that opens Photo Mode.
                if launching:
                    if name == "race_drive_throttle":
                        launching = False  # HUD confirmed -> normal racing below
                    elif name in (
                        "farm_wait_race_menu_focus",
                        "farm_wait_loading",
                        "farm_wait_unknown",
                    ) and (time.monotonic() - launch_since) <= 12.0:
                        in_race = True
                        if race_started is None:
                            race_started = time.monotonic()
                        pad.apply(throttle=1.0)
                        if not self._sleep(0.5):
                            break
                        continue
                    else:
                        launching = False  # results / pause / modal, or timed out

                # 1) Active race: hold throttle (state persists between cycles).
                if name == "race_drive_throttle":
                    in_race = True
                    self.race_hud_seen += 1
                    if race_started is None:
                        race_started = time.monotonic()
                    unknown_throttle_since = None
                    pad.apply(throttle=1.0)
                    if not self._sleep(self._race_poll_interval(race_started)):
                        break
                    continue

                # 1b) Ambiguous race start menu: detected race_menu but the
                #     start-focus text was not read. If we are NOT mid-race this
                #     is the start menu (its default focus is 开始赛事) -> press A
                #     to start; the launch window then holds throttle. We never
                #     press DpadUp (during launch/race this name is handled above
                #     as throttle, so A only fires from a real, idle start menu).
                if name == "farm_wait_race_menu_focus" and not in_race:
                    pad.neutral()
                    self.on_log("视觉刷图：识别到开始赛事菜单(焦点文字未读出)，按 A 开赛(默认焦点=开始赛事)。")
                    pad.tap("a", hold=0.15)
                    launching = True
                    launch_since = time.monotonic()
                    if not self._sleep(self._settle_for("farm_start_race")):
                        break
                    continue

                # 2) Loading/transition: never throttle, just wait.
                if name == "farm_wait_loading":
                    in_race = False
                    race_started = None
                    unknown_throttle_since = None
                    pad.neutral()
                    if not self._sleep(0.7):
                        break
                    continue

                # 3) Unknown or unconfirmed race-menu focus: if we were just
                #    racing, keep throttle briefly (transient mid-race frame);
                #    otherwise wait. Never press DpadUp here.
                if name in ("farm_wait_unknown", "farm_wait_race_menu_focus"):
                    if in_race:
                        if unknown_throttle_since is None:
                            unknown_throttle_since = time.monotonic()
                        if time.monotonic() - unknown_throttle_since <= 6.0:
                            pad.apply(throttle=1.0)
                            if not self._sleep(0.5):
                                break
                            continue
                        in_race = False
                        race_started = None
                        unknown_throttle_since = None
                    pad.neutral()
                    if not self._sleep(0.85):
                        break
                    continue

                # 4) A menu/modal action: release throttle, then a single tap.
                button = normalize_button(decision.button)
                in_race = False
                race_started = None
                unknown_throttle_since = None
                pad.neutral()
                if not button:
                    if not self._sleep(0.85):
                        break
                    continue
                if name in ("farm_restart_results", "farm_graceful_exit_results"):
                    self.laps += 1
                    self.on_log(f"视觉刷图：第 {self.laps} 圈完成。")
                self.on_log(f"视觉刷图按键：{decision.button} -> {button}；{name}。")
                pad.tap(button, hold=0.15)
                if name in ("farm_start_race", "farm_confirm_modal"):
                    # Confirming a start popup enters a fresh race just like
                    # farm_start_race, so open the launch window: hold throttle
                    # through the countdown/start-line frames that mis-read as
                    # race_menu/loading. (Never DpadUp -- that opens Photo Mode.)
                    launching = True
                    launch_since = time.monotonic()
                if name == "farm_graceful_exit_results" or (decision.terminal and self._graceful.is_set()):
                    self.exit_reason = self.exit_reason or "graceful_exit"
                    self._sleep(self._settle_for(name))
                    self.on_log("视觉刷图：平滑退出，已在结算/赛后页把控制权交回上层。")
                    break
                if not self._sleep(self._settle_for(name)):
                    break
        except Exception as exc:
            self.logger.exception("VisionFarmRunner crashed")
            self.on_log(f"视觉刷图运行出错：{exc}")
        finally:
            try:
                pad.neutral()
            except Exception:
                pass
            if self.laps > 0 and self.race_hud_seen == 0:
                self.on_log(
                    f"⚠ 视觉刷图核查：本轮起赛/重开 {self.laps} 次，但一帧驾驶画面(race_hud)都没识别到 —— "
                    "很可能没有真正跑赛(疑似对误判成结算页的画面反复按 X)，请核实是否真在刷分。"
                )
            else:
                self.on_log(
                    f"视觉刷图核查：本轮起赛/重开 {self.laps} 次，识别到驾驶画面 {self.race_hud_seen} 帧。"
                )
            self.on_log("视觉刷图已停止，手柄保持连接并已回正。")
