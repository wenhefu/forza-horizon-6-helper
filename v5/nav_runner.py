"""V5 event-driven navigation runner (phase 3b wiring).

Wires the three V5 engines into something runnable:
  recognize = V4Recognizer(capture_engine=CaptureEngine)  (continuous dxcam frames)
            + occlusion fallback (dxcam screen=="unknown" -> synchronous PrintWindow)
  decide    = v5.screen_registry.next_button(understanding, goal)
  press     = Gamepad.tap
driven by v5.reactor.EventReactor (press -> watch -> react, no fixed sleeps).

Same safety boundary as V1-V4: read-only capture + ViGEmBus input only; the game
must be in the foreground (no fake-focus). It NEVER presses unless you run it.

This is the experimental V5 navigation demo to live-test the felt latency; it
navigates the current screen to a goal (default the EventLab race-start menu) and
hands back. The full mode-three (buy + farm) stays on the proven V4 path.
"""
from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace

import focus
from gamepad import BUTTON_NAMES, Gamepad
from v4.decision import RouteContext, _is_start_race_focus, decide_mode3_navigation
from v4.farm_runner import VisionFarmRunner
from v4.recognizer import V4Recognizer
from v5.capture_engine import CaptureEngine
from v5.reactor import EventReactor
from v5.screen_registry import NextAction


def _background_understanding() -> SimpleNamespace:
    # Sentinel for "game not in foreground" -> next_button(spec=None) -> wait.
    return SimpleNamespace(
        screen="background", selected_item="", active_tab="",
        filter_state={}, scroll_state={}, ocr_regions=[],
    )


class V5Navigator:
    def __init__(
        self,
        title: str = "Forza",
        goal: str = "race_menu",
        on_log=None,
        logger=None,
        require_foreground: bool = True,
        auto_focus: bool = False,
        use_capture_engine: bool = True,
        downscale_width: int | None = 960,  # OCR drops ~3.5x at <=960 vs full; text still reads
        step_timeout: float = 2.5,
        stall_seconds: float = 30.0,
        max_seconds: float = 600.0,
        recognizer=None,
        pad=None,
        engine=None,
        decide_fn=None,
    ):
        self.title = title
        self.goal = goal
        self.on_log = on_log or (lambda message: None)
        self.logger = logger or logging.getLogger("forza6helper.v5.nav")
        self.require_foreground = require_foreground
        self.auto_focus = auto_focus
        self.downscale_width = downscale_width
        self.step_timeout = step_timeout
        self.stall_seconds = stall_seconds
        self.max_seconds = max_seconds
        if engine is not None:
            self.engine = engine
        else:
            self.engine = CaptureEngine(title, logger=self.logger) if use_capture_engine else None
        if recognizer is not None:
            self.recognizer = recognizer
        else:
            self.recognizer = V4Recognizer(title=title, capture_engine=self.engine, logger=self.logger)
        self._pad = pad
        self._stop = threading.Event()
        self.fallbacks = 0  # how many times dxcam unknown -> synchronous re-grab
        self._last_logged = None  # (screen, selected_item) we last logged
        self._unknown_backouts = 0  # consecutive B presses to escape unknown screens
        self._cap_ms_sum = 0.0  # total recognition time (to report avg latency)
        self._cap_n = 0
        # Drive the reactor with the PROVEN decide_mode3_navigation (correct routes +
        # focus handling); the generic registry BFS is naive for focus-based menus.
        # The registry stays for recovery (unknown-screen back-out) only.
        self._ctx = RouteContext()
        self._decide_fn = decide_fn or (lambda u: decide_mode3_navigation(u, self._ctx))

    # -- wiring ------------------------------------------------------------
    def _get_pad(self):
        if self._pad is None:
            self._pad = Gamepad(logger=self.logger)
        return self._pad

    def recognize(self):
        if self.require_foreground and not focus.is_foreground(self.title):
            return _background_understanding()
        # Full OCR is needed for the favorite-filter / my-cars screens (full_ocr=False
        # misreads the filter page as idle_showcase and the filter step loops). Slower
        # but correct -- recognition-speed optimization (downscale-for-OCR) is a
        # separate focused task. skip_smart drops the unused V1 pixel-loop detector.
        snap = self.recognizer.capture(
            full_ocr=True, region_ocr=True, skip_smart=True, downscale_width=self.downscale_width
        )
        if getattr(snap, "capture_method", "") == "dxcam" and str(snap.v3.screen) == "unknown":
            # dxcam captures on-screen pixels; an overlapping window reads as unknown.
            # Re-grab synchronously (PrintWindow renders the window's own content).
            self.fallbacks += 1
            snap = self.recognizer.capture(
                full_ocr=True, region_ocr=True, max_age_ms=0.0, skip_smart=True,
                downscale_width=self.downscale_width,
            )
        self._cap_ms_sum += float(getattr(snap, "elapsed_ms", 0.0) or 0.0)
        self._cap_n += 1
        return snap.v3

    def _update_context(self, understanding) -> None:
        # Mirror V4Mode3Runner._update_context_from_snapshot for the favorite filter.
        filter_state = getattr(understanding, "filter_state", {}) or {}
        screen = str(getattr(understanding, "screen", "") or "")
        if screen == "eventlab_filter" and filter_state.get("favorite_checked") is True:
            self._ctx.favorite_filter_checked = True
        if screen == "eventlab_my_cars" and self._ctx.favorite_filter_checked:
            self._ctx.favorite_filter_done = True

    def decide(self, understanding):
        self._update_context(understanding)
        screen = str(getattr(understanding, "screen", "") or "")
        selected = str(getattr(understanding, "selected_item", "") or "")
        # Arrival by FOCUS, not screen label: the start-race menu sometimes reads as
        # pause_story (not race_menu), but a focused 开始赛事/开始竞赛赛事 tile means we
        # are at the goal (same signal decide_farm_loop trusts).
        if self.goal in ("race_menu", "prestart") and _is_start_race_focus(selected):
            action = NextAction("", "已到达开始赛事菜单（焦点=开始赛事）。", name="arrived")
        else:
            action = self._decide_fn(understanding)  # decide_mode3_navigation
        if (screen, selected) != self._last_logged:
            self._last_logged = (screen, selected)
            self.on_log(
                f"  识别：{screen or '?'} 焦点={selected or '空'} → "
                f"{getattr(action, 'name', '')} 按 {getattr(action, 'button', '') or '—'}"
            )
        if str(getattr(action, "name", "")) == "wait_unknown":
            # A screen the proven nav does not handle (coverage gap): back out (B)
            # toward a known screen instead of stalling -- bounded so a screen B
            # cannot change does not loop forever.
            self._unknown_backouts += 1
            if self._unknown_backouts <= 6:
                return NextAction(
                    "B",
                    f"未知界面 {screen!r}，按 B 退回已知界面（{self._unknown_backouts}/6）。",
                    name="recover_backout",
                )
            return action  # give up after the cap -> stall (lets the watchdog stop it)
        self._unknown_backouts = 0
        return action

    def press(self, button: str) -> None:
        if button not in BUTTON_NAMES:
            self.on_log(f"V5 导航：忽略未知按键 {button!r}。")
            return
        self._get_pad().tap(button, hold=0.12)

    # -- run ---------------------------------------------------------------
    def run(self):
        self.on_log(f"V5 事件驱动导航启动：目标={self.goal}，引擎={'dxcam' if self.engine else 'off'}。")
        if self.auto_focus:
            # Normal foreground switch (same as V4 --auto-focus / "切回游戏"): a real
            # title-bar activation, NOT a fake-focus message. Stays in-boundary.
            try:
                focus.activate_window(self.title, on_log=self.on_log, logger=self.logger)
            except Exception as exc:
                self.on_log(f"切回游戏失败：{exc}")
        if self.engine is not None:
            started = self.engine.start()
            self.on_log("抓帧引擎：" + ("dxcam 已启动（连续抓帧）。" if started else "dxcam 不可用，回退同步抓图。"))
        try:
            reactor = EventReactor(
                self.recognize, self.decide, self.press,
                on_log=self.on_log, step_timeout=self.step_timeout,
                stall_seconds=self.stall_seconds, stop_event=self._stop,
            )
            result = reactor.run(max_seconds=self.max_seconds)
            avg_ms = (self._cap_ms_sum / self._cap_n) if self._cap_n else 0.0
            self.on_log(
                f"V5 导航结束：reason={result.reason} 步数={result.steps} "
                f"用时={result.elapsed_s:.1f}s 最后画面={result.last_screen} 遮挡回退={self.fallbacks} 次 "
                f"平均识别={avg_ms:.0f}ms（{self._cap_n} 帧）。"
            )
            return result
        finally:
            if self._pad is not None:
                try:
                    self._pad.neutral()
                except Exception:
                    pass
            if self.engine is not None:
                self.engine.stop()

    def stop(self):
        self._stop.set()


class V5Session:
    """A complete V5 cycle: event-driven nav -> proven VisionFarmRunner farm.

    The buy phase still uses the proven V4 path (not included here); this session
    proves the V5 navigation and hands a CONFIRMED start-race menu to the proven
    farm runner, reusing the SAME recognizer + pad (so no controller reconnect
    between nav and farm).
    """

    def __init__(
        self,
        title: str = "Forza",
        goal: str = "race_menu",
        farm_minutes: float = 0.0,
        on_log=None,
        logger=None,
        auto_focus: bool = False,
        require_foreground: bool = True,
        use_capture_engine: bool = False,
        downscale_width: int | None = 960,
        max_seconds: float = 600.0,
        nav=None,
    ):
        self.on_log = on_log or (lambda message: None)
        self.farm_seconds = max(0.0, float(farm_minutes) * 60.0)
        self.auto_focus = auto_focus
        self.require_foreground = require_foreground
        self.nav = nav if nav is not None else V5Navigator(
            title=title, goal=goal, on_log=self.on_log, logger=logger, auto_focus=auto_focus,
            require_foreground=require_foreground, use_capture_engine=use_capture_engine,
            downscale_width=downscale_width, max_seconds=max_seconds,
        )
        self._farm = None

    def run(self):
        result = self.nav.run()
        if getattr(result, "reason", "") != "goal":
            self.on_log(f"V5 会话：导航未到达开始赛事菜单（{getattr(result, 'reason', '?')}），不进入刷图。")
            return result
        if self.farm_seconds <= 0:
            self.on_log("V5 会话：已到开始赛事菜单；未设置刷图时长，结束。")
            return result
        self.on_log(
            f"V5 会话：到达开始赛事菜单，交给证明过的 VisionFarmRunner 刷图约 {self.farm_seconds / 60:.1f} 分钟。"
        )
        self._farm = VisionFarmRunner(
            title=self.nav.title, recognizer=self.nav.recognizer, on_log=self.on_log,
            logger=self.nav.logger, pad_provider=lambda: self.nav._get_pad(),
        )
        self._farm.start(
            total_seconds=self.farm_seconds, auto_focus=self.auto_focus,
            require_foreground=self.require_foreground,
        )
        while self._farm.is_running():
            time.sleep(0.3)
        self.on_log(
            f"V5 会话：刷图结束（{self._farm.exit_reason or 'done'}），共 {self._farm.laps} 圈，"
            f"驾驶帧 {self._farm.race_hud_seen}。"
        )
        return result

    def stop(self):
        self.nav.stop()
        if self._farm is not None:
            self._farm.stop()
