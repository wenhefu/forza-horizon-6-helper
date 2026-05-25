"""Combined buy-car and EventLab farming flow."""
import logging
import threading
import time

import config
import focus
from buy_car_detector import (
    STATE_CONFIRM_MODAL,
    STATE_CONTROLLER_DISCONNECTED,
    STATE_CREATIVE_HUB,
    STATE_EVENTLAB_EVENTS,
    STATE_EVENTLAB_FAVORITES,
    STATE_EVENTLAB_MENU,
    STATE_EVENTLAB_FILTER,
    STATE_EVENTLAB_MY_CARS,
    STATE_EVENTLAB_MY_CARS_22B_READY,
    STATE_EVENTLAB_RACE_TYPE,
    STATE_PAUSE_MENU,
    STATE_SKILL_POINTS_EXHAUSTED,
)
from buy_car_runner import BuyCarRunner
from screen_detector import (
    STATE_PRESTART,
    STATE_PRESTART_WRONG_SELECTION,
)
from smart_runner import SmartRunner


class ComboRunner:
    """Buy Subaru 22B until points run out, then route into EventLab farming."""

    def __init__(self, on_log=None, logger=None, pad_provider=None):
        self.on_log = on_log or (lambda msg: None)
        self.logger = logger or logging.getLogger("forza6helper")
        self.pad_provider = pad_provider
        self.buy_runner = BuyCarRunner(on_log=self.on_log, logger=self.logger, pad_provider=pad_provider)
        self.smart_runner = SmartRunner(on_log=self.on_log, logger=self.logger, pad_provider=pad_provider)
        self._thread = None
        self._stop = threading.Event()

    def is_running(self):
        return (
            self._thread is not None
            and self._thread.is_alive()
        ) or self.buy_runner.is_running() or self.smart_runner.is_running()

    def start(self, startup_delay=0.0, total_seconds=None, auto_focus=True, require_foreground=True):
        if self.is_running():
            self.logger.info("ComboRunner start ignored because it is already running")
            return
        self._stop.clear()
        self.logger.info(
            "ComboRunner starting startup_delay=%.2f total_seconds=%s auto_focus=%s require_foreground=%s",
            startup_delay,
            "unlimited" if total_seconds is None else f"{total_seconds:.2f}",
            auto_focus,
            require_foreground,
        )
        self._thread = threading.Thread(
            target=self._run,
            args=(startup_delay, total_seconds, auto_focus, require_foreground),
            name="combo-runner",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self.logger.info("ComboRunner stop requested")
        self._stop.set()
        self.buy_runner.stop()
        self.smart_runner.stop()

    def detect_once(self):
        return self.buy_runner.detect_once()

    def _sleep(self, seconds):
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._stop.is_set():
                return False
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))
        return not self._stop.is_set()

    def _remaining(self, started, total_seconds):
        if total_seconds is None:
            return None
        remaining = total_seconds - (time.monotonic() - started)
        return max(0.0, remaining)

    def _tap(self, pad, button, hold=0.15, after=0.75):
        self.buy_runner._invalidate_ocr()
        pad.tap(button, hold=hold)
        self.buy_runner._invalidate_ocr()
        return self._sleep(after)

    def _tap_many(self, pad, button, count, after_each=0.55):
        for _ in range(count):
            if not self._tap(pad, button, hold=0.12, after=after_each):
                return False
        return True

    def _ensure_foreground(self, auto_focus, require_foreground):
        if not require_foreground or focus.is_foreground(config.GAME_TITLE):
            return True
        self.on_log("组合模式：游戏不在前台，先暂停输入并尝试切回。")
        if auto_focus:
            focus.activate_window(
                title_substr=config.GAME_TITLE,
                on_log=self.on_log,
                logger=self.logger,
            )
        return self._sleep(1.0)

    def _run(self, startup_delay, total_seconds, auto_focus, require_foreground):
        try:
            pad = self.pad_provider()
        except Exception as exc:
            self.logger.exception("Unable to start combo runner gamepad")
            self.on_log(f"无法启动虚拟手柄：{exc}")
            return

        started = time.monotonic()
        cycle = 0
        try:
            if startup_delay > 0:
                self.on_log(
                    f"{startup_delay:.0f} 秒后开始组合模式：买车加点点完→EventLab 刷分→回到自由漫游→再去买车，循环往复。"
                )
                if not self._sleep(startup_delay):
                    return

            while not self._stop.is_set():
                cycle += 1
                remaining = self._remaining(started, total_seconds)
                if remaining is not None and remaining <= 0:
                    self.on_log("组合模式：总运行时间已到，停止循环。")
                    return

                eventlab_ready = self._try_resume_eventlab_prestart(
                    pad,
                    auto_focus,
                    require_foreground,
                )
                if not eventlab_ready:
                    self.on_log(f"组合模式：第 {cycle} 轮买车加点阶段开始，直到检测到技术点数不足。")
                    if not self._run_buy_phase(remaining, auto_focus, require_foreground):
                        return  # stop reason wasn't points_exhausted, or user stopped

                    remaining = self._remaining(started, total_seconds)
                    if remaining is not None and remaining <= 0:
                        self.on_log("组合模式：买车阶段完成时总时间已到，不再进入 EventLab。")
                        return

                    if not self._navigate_to_eventlab_prestart(pad, auto_focus, require_foreground):
                        self.on_log("组合模式：没有稳定进入 EventLab 开始赛事菜单，已停止，避免乱按。")
                        return
                else:
                    self.on_log("组合模式：已从当前 EventLab 页面续接到开始赛事菜单。")

                remaining = self._remaining(started, total_seconds)
                if remaining is not None and remaining <= 0:
                    self.on_log("组合模式：进入 EventLab 时总时间已到，不再启动刷分。")
                    return

                farm_seconds = float(getattr(config, "COMBO_EVENTLAB_FARM_SECONDS", 90 * 60))
                if remaining is not None:
                    farm_seconds = min(farm_seconds, remaining)
                if not self._run_farm_phase(farm_seconds, auto_focus, require_foreground):
                    return  # user stopped during farming

                if self._stop.is_set():
                    return

                remaining = self._remaining(started, total_seconds)
                if remaining is not None and remaining <= 0:
                    self.on_log("组合模式：刷分阶段结束时总时间已到，不再回到买车阶段。")
                    return

                # EventLab leg done. Get back to the pause menu so the next
                # iteration of the buy phase can pick up cleanly.
                if not self._exit_eventlab_to_pause_menu(pad, auto_focus, require_foreground):
                    self.on_log("组合模式：没办法稳定回到暂停菜单，已停止，下一轮买车不启动。")
                    return

                self.on_log(f"组合模式：第 {cycle} 轮完成，准备进入第 {cycle + 1} 轮买车加点。")
        except Exception as exc:
            self.logger.exception("ComboRunner crashed")
            self.on_log(f"组合模式运行时出错：{exc}")
        finally:
            if self._stop.is_set():
                self.buy_runner.stop()
                self.smart_runner.stop()
            pad.neutral()
            self.on_log("组合模式已停止，手柄保持连接并已回正。")

    def _run_buy_phase(self, remaining, auto_focus, require_foreground):
        self.buy_runner.start(
            startup_delay=0.0,
            total_seconds=remaining,
            auto_focus=auto_focus,
            require_foreground=require_foreground,
        )
        while self.buy_runner.is_running() and not self._stop.is_set():
            if not self._sleep(0.25):
                break
        if self._stop.is_set():
            return False
        if self.buy_runner.stop_reason != "points_exhausted":
            self.on_log(
                f"组合模式：买车阶段停止原因={self.buy_runner.stop_reason or '总时间到/未知'}，先不继续切 EventLab。"
            )
            return False
        self.on_log("组合模式：确认是技术点数不足，开始退回自由漫游并打开 EventLab。")
        return True

    def _run_farm_phase(self, farm_seconds, auto_focus, require_foreground):
        self.on_log(
            f"组合模式：已到 EventLab 开始赛事菜单，交给刷技能点模式跑 {farm_seconds / 60:.0f} 分钟"
            "（到点后会等当前比赛跑完再按 A 退出，不会突然中断比赛）。"
        )
        self.smart_runner.start(
            startup_delay=0.0,
            total_seconds=farm_seconds,
            auto_focus=auto_focus,
            require_foreground=require_foreground,
        )
        while self.smart_runner.is_running() and not self._stop.is_set():
            if not self._sleep(0.25):
                break
        if self._stop.is_set():
            return False
        self.on_log(
            f"组合模式：刷技能点模式已结束（原因={self.smart_runner.exit_reason or '未知'}）。"
        )
        return True

    def _exit_eventlab_to_pause_menu(self, pad, auto_focus, require_foreground):
        # SmartRunner just pressed A on the results page. Forza typically
        # animates back to either free roam or an event hub menu over a few
        # seconds; let it settle before we try to detect anything.
        initial_wait = float(getattr(config, "COMBO_EXIT_TO_PAUSE_INITIAL_WAIT", 5.0))
        self.on_log(
            f"组合模式：等待 {initial_wait:.0f} 秒让游戏从结算页过渡，再尝试打开暂停菜单。"
        )
        if not self._sleep(initial_wait):
            return False

        max_attempts = int(getattr(config, "COMBO_EXIT_TO_PAUSE_MAX_ATTEMPTS", 8))
        recovery_wait = float(getattr(config, "COMBO_EXIT_TO_PAUSE_A_WAIT", 2.0))

        for attempt in range(1, max_attempts + 1):
            if self._stop.is_set():
                return False

            # Early-out if the pause menu somehow opened already (e.g. user
            # opened it manually, or a previous Menu tap took effect late).
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False
            self.logger.info(
                "Combo exit-to-pause attempt=%d pre-menu state=%s confidence=%.3f",
                attempt,
                detection.state,
                detection.confidence,
            )
            if detection.state == STATE_PAUSE_MENU:
                self.on_log("组合模式：已经在暂停菜单，不再额外按 Menu。")
                return True
            if detection.state == STATE_CONTROLLER_DISCONNECTED:
                self.on_log("组合模式：检测到控制器未连接弹窗，按 A 恢复。")
                if not self._tap(pad, "a", after=1.0):
                    return False
                continue

            self.on_log(
                f"组合模式：尝试按 Menu 打开暂停菜单（第 {attempt}/{max_attempts} 次）。"
            )
            if not self._tap(pad, "start", after=1.5):
                return False

            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False
            self.logger.info(
                "Combo exit-to-pause attempt=%d post-menu state=%s confidence=%.3f",
                attempt,
                detection.state,
                detection.confidence,
            )
            if detection.state == STATE_PAUSE_MENU:
                self.on_log("组合模式：已确认暂停菜单，移交给买车阶段。")
                return True

            # Menu didn't get us to the pause menu, so we probably weren't in
            # free roam yet — still on some EventLab post-race menu. Press A to
            # advance past it (e.g. "继续" prompt), wait, then try Menu again.
            self.on_log(
                f"组合模式：当前状态 {detection.state}，按 Menu 没到暂停菜单，再按 A 推进一下。"
            )
            if not self._tap(pad, "a", after=recovery_wait):
                return False

        self.on_log("组合模式：连续按 Menu/A 都没回到暂停菜单，放弃这轮循环。")
        return False

    def _navigate_to_eventlab_prestart(self, pad, auto_focus, require_foreground):
        if not self._ensure_foreground(auto_focus, require_foreground):
            return False

        # We should be on the "not enough skill points" modal. Close it, then back
        # out through mastery -> upgrade -> vehicle -> free roam.
        if not self._confirm_or_close_points_modal(pad, auto_focus, require_foreground):
            return False
        if not self._tap(pad, "b", after=1.0):
            return False
        if not self._tap(pad, "b", after=1.0):
            return False
        if not self._tap(pad, "b", after=1.8):
            return False

        self.on_log("组合模式：已退到自由漫游附近，按 Menu 打开暂停菜单。")
        if not self._tap(pad, "start", after=1.3):
            return False

        if not self._wait_buy_state("暂停菜单", {STATE_PAUSE_MENU}, timeout=8.0, auto_focus=auto_focus, require_foreground=require_foreground):
            self.on_log("组合模式：未确认暂停菜单，补按一次 Menu。")
            if not self._tap(pad, "start", after=1.3):
                return False
            self._wait_buy_state("暂停菜单", {STATE_PAUSE_MENU}, timeout=4.0, auto_focus=auto_focus, require_foreground=require_foreground)

        if not self._move_to_creative_hub(pad, auto_focus, require_foreground):
            return False

        self.on_log("组合模式：创意中心页按 A 进入 EventLab。")
        if not self._tap(pad, "a", after=1.5):
            return False
        if not self._wait_buy_state("EventLab 首页", {STATE_EVENTLAB_MENU}, timeout=8.0, auto_focus=auto_focus, require_foreground=require_foreground):
            return False

        self.on_log("组合模式：EventLab 首页按 A 进入赛事。")
        if not self._tap(pad, "a", after=1.6):
            return False
        if not self._wait_buy_state("EventLab 赛事页", {STATE_EVENTLAB_EVENTS, STATE_EVENTLAB_FAVORITES}, timeout=10.0, auto_focus=auto_focus, require_foreground=require_foreground):
            return False

        if not self._move_to_eventlab_favorites(pad, auto_focus, require_foreground):
            return False

        self.on_log("组合模式：收藏赛事页按 A 进入当前收藏的刷分图。")
        if not self._tap(pad, "a", after=2.0):
            return False
        if not self._wait_buy_state(
            "比赛类型弹窗或我的车辆页",
            {STATE_EVENTLAB_RACE_TYPE, STATE_EVENTLAB_MY_CARS, STATE_EVENTLAB_MY_CARS_22B_READY},
            timeout=8.0,
            auto_focus=auto_focus,
            require_foreground=require_foreground,
            pad=pad,
        ):
            return False

        detection = self._detect_buy(auto_focus, require_foreground)
        if detection and detection.state == STATE_EVENTLAB_RACE_TYPE:
            self.on_log("组合模式：比赛类型保持“单人”，按 A。")
            if not self._tap(pad, "a", after=2.0):
                return False
            if not self._wait_buy_state("EventLab 我的车辆页", {STATE_EVENTLAB_MY_CARS, STATE_EVENTLAB_MY_CARS_22B_READY}, timeout=12.0, auto_focus=auto_focus, require_foreground=require_foreground, pad=pad):
                return False
        else:
            self.on_log("组合模式：已经跳过比赛类型，当前在我的车辆页。")

        if not self._apply_favorite_filter(pad, auto_focus, require_foreground):
            return False
        if not self._select_eventlab_22b(pad, auto_focus, require_foreground):
            return False
        return self._wait_for_prestart(pad, auto_focus, require_foreground)

    def _try_resume_eventlab_prestart(self, pad, auto_focus, require_foreground):
        """Resume cleanly when the previous run stopped inside EventLab."""
        if not self._ensure_foreground(auto_focus, require_foreground):
            return False

        try:
            smart_detection = self.smart_runner.detect_once()
        except Exception as exc:
            self.logger.warning("Combo resume smart detection failed: %s", exc)
            smart_detection = None
        if smart_detection and smart_detection.state in (STATE_PRESTART, STATE_PRESTART_WRONG_SELECTION):
            self.on_log("组合模式：启动时已在 EventLab 开始赛事菜单，直接续接刷分。")
            return True

        detection = self._detect_buy(auto_focus, require_foreground)
        if detection is None:
            return False

        resumable_states = {
            STATE_EVENTLAB_MENU,
            STATE_EVENTLAB_EVENTS,
            STATE_EVENTLAB_FAVORITES,
            STATE_EVENTLAB_RACE_TYPE,
            STATE_EVENTLAB_MY_CARS,
            STATE_EVENTLAB_MY_CARS_22B_READY,
            STATE_EVENTLAB_FILTER,
        }
        if detection.state not in resumable_states:
            return False

        self.on_log(f"组合模式：启动时检测到 EventLab 中途页面 {detection.state}，尝试从这里续接。")

        if detection.state == STATE_EVENTLAB_FILTER:
            self.on_log("组合模式：当前在筛选弹窗，先按 B 回到我的车辆页。")
            if not self._tap(pad, "b", after=1.0):
                return False
            if not self._wait_buy_state(
                "EventLab 我的车辆页",
                {STATE_EVENTLAB_MY_CARS, STATE_EVENTLAB_MY_CARS_22B_READY},
                timeout=6.0,
                auto_focus=auto_focus,
                require_foreground=require_foreground,
                pad=pad,
            ):
                return False
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False

        if detection.state == STATE_EVENTLAB_MENU:
            self.on_log("组合模式：已在 EventLab 首页，按 A 进入赛事页继续。")
            if not self._tap(pad, "a", after=1.6):
                return False
            if not self._wait_buy_state(
                "EventLab 赛事页",
                {STATE_EVENTLAB_EVENTS, STATE_EVENTLAB_FAVORITES},
                timeout=10.0,
                auto_focus=auto_focus,
                require_foreground=require_foreground,
                pad=pad,
            ):
                return False
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False

        if detection.state == STATE_EVENTLAB_EVENTS:
            if not self._move_to_eventlab_favorites(pad, auto_focus, require_foreground):
                return False
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False

        if detection.state == STATE_EVENTLAB_FAVORITES:
            self.on_log("组合模式：已在 EventLab 我的收藏，按 A 进入当前收藏赛事。")
            if not self._tap(pad, "a", after=2.0):
                return False
            if not self._wait_buy_state(
                "比赛类型弹窗或我的车辆页",
                {STATE_EVENTLAB_RACE_TYPE, STATE_EVENTLAB_MY_CARS, STATE_EVENTLAB_MY_CARS_22B_READY},
                timeout=8.0,
                auto_focus=auto_focus,
                require_foreground=require_foreground,
                pad=pad,
            ):
                return False
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False

        if detection.state == STATE_EVENTLAB_RACE_TYPE:
            self.on_log("组合模式：比赛类型保持“单人”，按 A。")
            if not self._tap(pad, "a", after=2.0):
                return False
            if not self._wait_buy_state(
                "EventLab 我的车辆页",
                {STATE_EVENTLAB_MY_CARS, STATE_EVENTLAB_MY_CARS_22B_READY},
                timeout=12.0,
                auto_focus=auto_focus,
                require_foreground=require_foreground,
                pad=pad,
            ):
                return False
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False

        if detection.state == STATE_EVENTLAB_MY_CARS:
            if not self._apply_favorite_filter(pad, auto_focus, require_foreground):
                return False
            return self._select_eventlab_22b(pad, auto_focus, require_foreground)

        if detection.state == STATE_EVENTLAB_MY_CARS_22B_READY:
            return self._select_eventlab_22b(pad, auto_focus, require_foreground)

        return False

    def _confirm_or_close_points_modal(self, pad, auto_focus, require_foreground):
        detection = self._detect_buy(auto_focus, require_foreground)
        if detection and detection.state == STATE_SKILL_POINTS_EXHAUSTED:
            self.on_log("组合模式：点数不足弹窗已确认，按 A 关闭。")
        else:
            self.on_log("组合模式：准备按 A 关闭当前弹窗，再回到熟练度页。")
        return self._tap(pad, "a", after=1.0)

    def _move_to_creative_hub(self, pad, auto_focus, require_foreground):
        max_presses = 6
        self.on_log(
            f"组合模式：切到创意中心，识别到就停，最多按 {max_presses} 次 RB。"
        )
        for press_index in range(0, max_presses + 1):
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False
            self.logger.info(
                "Combo move-to-creative attempt=%d state=%s confidence=%.3f",
                press_index,
                detection.state,
                detection.confidence,
            )
            if detection.state == STATE_CREATIVE_HUB:
                self.on_log("组合模式：已确认创意中心。")
                return True
            if press_index >= max_presses:
                break
            self.on_log(
                f"组合模式：当前状态 {detection.state}，还没到创意中心，按 RB（{press_index + 1}/{max_presses}）。"
            )
            if not self._tap(pad, "rb", after=0.7):
                return False
        self.on_log("组合模式：未能确认创意中心，停止在当前页面。")
        return False

    def _move_to_eventlab_favorites(self, pad, auto_focus, require_foreground):
        max_presses = 12
        self.on_log(
            f"组合模式：切到 EventLab 我的收藏，识别到就停，最多按 {max_presses} 次 RB。"
        )
        for press_index in range(0, max_presses + 1):
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False
            self.logger.info(
                "Combo move-to-favorites attempt=%d state=%s confidence=%.3f",
                press_index,
                detection.state,
                detection.confidence,
            )
            if detection.state == STATE_EVENTLAB_FAVORITES:
                self.on_log("组合模式：已确认我的收藏。")
                return True
            active_tab = int(detection.scores.get("ocr_eventlab_active_tab", 0.0) or 0)
            if active_tab == 7:
                self.on_log("组合模式：顶部高亮已经是我的收藏，按当前页继续。")
                return True
            if press_index >= max_presses:
                break
            if active_tab > 7:
                button = "lb"
                direction = "LB 回退"
            else:
                button = "rb"
                direction = "RB 前进"
            self.on_log(
                f"组合模式：当前状态 {detection.state}，active_tab={active_tab or '未知'}，还没到我的收藏，按 {direction}（{press_index + 1}/{max_presses}）。"
            )
            if not self._tap(pad, button, after=0.8):
                return False
        self.on_log("组合模式：未能确认我的收藏，停止在当前页面。")
        return False

    def _apply_favorite_filter(self, pad, auto_focus, require_foreground):
        # The filter checkbox state is hard to read reliably (the existing
        # color sample sits at the wrong pixel and can return either value),
        # so use a deterministic reset-then-check sequence:
        #   Y  -> open filter
        #   X  -> reset all filters (everything becomes unchecked)
        #   A  -> toggle 收藏 on (cursor defaults to the 收藏 row when opening)
        #   B  -> close the popup
        # This way we always end with exactly "收藏" enabled, regardless of any
        # filters the user (or a previous run) left behind.
        self.on_log("组合模式：我的车辆页按 Y 打开筛选弹窗。")
        if not self._tap(pad, "y", after=1.0):
            return False
        if not self._wait_buy_state(
            "车辆筛选弹窗",
            {STATE_EVENTLAB_FILTER},
            timeout=8.0,
            auto_focus=auto_focus,
            require_foreground=require_foreground,
            pad=pad,
        ):
            # Y might have been swallowed if the page was still settling. Retry once.
            self.on_log("组合模式：第一次 Y 没看到筛选弹窗，再按一次 Y。")
            if not self._tap(pad, "y", after=1.0):
                return False
            if not self._wait_buy_state(
                "车辆筛选弹窗",
                {STATE_EVENTLAB_FILTER},
                timeout=6.0,
                auto_focus=auto_focus,
                require_foreground=require_foreground,
                pad=pad,
            ):
                return False

        self.on_log("组合模式：按 X 重置筛选，确保只剩“收藏”需要打勾。")
        if not self._tap(pad, "x", after=0.8):
            return False

        # After X reset, we should still be on the filter popup with the cursor
        # on 收藏. Confirm we are still in FILTER state before pressing A.
        detection = self._detect_buy(auto_focus, require_foreground)
        if detection is None:
            return False
        if detection.state != STATE_EVENTLAB_FILTER:
            self.on_log(
                f"组合模式：按 X 后状态变成 {detection.state}，重新尝试打开筛选弹窗。"
            )
            if not self._tap(pad, "y", after=1.0):
                return False
            if not self._wait_buy_state(
                "车辆筛选弹窗",
                {STATE_EVENTLAB_FILTER},
                timeout=6.0,
                auto_focus=auto_focus,
                require_foreground=require_foreground,
                pad=pad,
            ):
                return False

        self.on_log("组合模式：按 A 勾选“收藏”。")
        if not self._tap(pad, "a", after=0.8):
            return False

        # Verify (best-effort) the checkbox now reports checked. If not, we
        # still press B – the worst case is the unfiltered list is shown, but
        # _select_eventlab_22b can still find 22B by OCR text.
        detection_after = self._detect_buy(auto_focus, require_foreground)
        if detection_after and detection_after.state == STATE_EVENTLAB_FILTER:
            if detection_after.scores.get("ocr_eventlab_filter_favorite_checked", 0.0) >= 0.5:
                self.on_log("组合模式：已识别到“收藏”勾选。")
            else:
                self.on_log("组合模式：色块检查没确认勾选，相信按键序列已勾上。")

        if not self._tap(pad, "b", after=1.4):
            return False
        return self._wait_buy_state(
            "筛选后的我的车辆页",
            {STATE_EVENTLAB_MY_CARS, STATE_EVENTLAB_MY_CARS_22B_READY},
            timeout=10.0,
            auto_focus=auto_focus,
            require_foreground=require_foreground,
            pad=pad,
        )

    def _select_eventlab_22b(self, pad, auto_focus, require_foreground):
        self.on_log("组合模式：在我的车辆页用 OCR+高亮定位 22B，确认选中后再按 A。")
        last_move = None
        target_missing_after_move = False
        unknown_selected_count = 0
        delta_zero_streak = 0  # consecutive frames where target_col == selected_col

        for attempt in range(1, 22):
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False

            if detection.state == STATE_EVENTLAB_MY_CARS_22B_READY:
                self.on_log("组合模式：我的车辆页已确认 22B 高亮，按 A 选择。")
                if not self._tap(pad, "a", after=2.0):
                    return False
                if self._wait_for_prestart(pad, auto_focus, require_foreground):
                    return True
                detection_after = self._detect_buy(auto_focus, require_foreground)
                if detection_after and detection_after.state == STATE_EVENTLAB_MY_CARS_22B_READY:
                    self.on_log("组合模式：选择 22B 后仍在车辆页，补按一次 A。")
                    if not self._tap(pad, "a", after=2.0):
                        return False
                    return self._wait_for_prestart(pad, auto_focus, require_foreground)
                return False

            if detection.state != STATE_EVENTLAB_MY_CARS:
                if detection.state == STATE_CONTROLLER_DISCONNECTED:
                    self.on_log("组合模式：选车时遇到控制器弹窗，按 A 恢复。")
                    if not self._tap(pad, "a", after=1.0):
                        return False
                    continue
                if detection.state == STATE_EVENTLAB_FILTER:
                    self.on_log("组合模式：仍在筛选弹窗，按 B 回车辆页。")
                    if not self._tap(pad, "b", after=1.0):
                        return False
                    continue
                self.on_log(f"组合模式：选车时页面状态是 {detection.state}，等待重新识别，不乱按。")
                if not self._sleep(0.8):
                    return False
                continue

            target_col = int(detection.scores.get("ocr_eventlab_22b_target_col", 0.0))
            selected_col = int(detection.scores.get("ocr_eventlab_selected_col", 0.0))
            target_seen = detection.scores.get("ocr_eventlab_22b_target_text_seen", 0.0) >= 0.5

            if not target_seen:
                if last_move and not target_missing_after_move:
                    rollback = self.buy_runner._opposite_move(last_move)
                    target_missing_after_move = True
                    self.on_log(f"组合模式：上一步后 22B 不在页面，回退 {self.buy_runner._move_label(rollback)}。")
                    if not self._tap(pad, rollback, after=0.8):
                        return False
                    continue
                self.on_log(f"组合模式：我的车辆页暂未看到 22B，按右搜索（第 {attempt} 次）。")
                last_move = "dpad_right"
                target_missing_after_move = False
                if not self._tap(pad, "dpad_right", after=0.8):
                    return False
                continue

            target_missing_after_move = False
            if not selected_col:
                unknown_selected_count += 1
                if unknown_selected_count >= 3:
                    self.on_log("组合模式：看到 22B 但识别不到当前高亮，轻按左/右触发高亮刷新。")
                    unknown_selected_count = 0
                    last_move = "dpad_left"
                    if not self._tap(pad, "dpad_left", after=0.8):
                        return False
                else:
                    self.on_log("组合模式：看到 22B 但未识别当前高亮，等待下一张图，不按方向键。")
                    if not self._sleep(0.8):
                        return False
                continue

            unknown_selected_count = 0
            delta = target_col - selected_col
            if delta == 0:
                delta_zero_streak += 1
                if delta_zero_streak >= 3:
                    # The OCR text column and the selected highlight column have
                    # agreed three frames in a row. Even though the lime ratio
                    # check failed to upgrade the state to MY_CARS_22B_READY
                    # (the "current car" yellow border can be thinner than the
                    # cursor highlight), we trust the column match and press A.
                    self.on_log(
                        "组合模式：22B 文本列和高亮列连续 3 帧一致，按 A 选择 22B。"
                    )
                    if not self._tap(pad, "a", after=2.0):
                        return False
                    if self._wait_for_prestart(pad, auto_focus, require_foreground):
                        return True
                    self.on_log("组合模式：按 A 后未进入开始赛事菜单，回到选车页继续观察。")
                    delta_zero_streak = 0
                    continue
                self.on_log(
                    f"组合模式：22B 文本列和高亮列一致（第 {delta_zero_streak}/3 次确认）。"
                )
                if not self._sleep(0.7):
                    return False
                continue

            delta_zero_streak = 0
            button = "dpad_right" if delta > 0 else "dpad_left"
            last_move = button
            self.on_log(
                f"组合模式：22B 在第 {target_col} 张，当前第 {selected_col} 张，移动 {self.buy_runner._move_label(button)} 1 格。"
            )
            if not self._tap(pad, button, after=0.8):
                return False

        self.on_log("组合模式：多次尝试仍未稳定选中 22B，停止在车辆页，避免误进其它车。")
        return False

    def _wait_buy_state(self, label, target_states, timeout, auto_focus, require_foreground, pad=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stop.is_set():
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False
            self.logger.info(
                "Combo wait %s state=%s confidence=%.3f",
                label,
                detection.state,
                detection.confidence,
            )
            if detection.state in target_states:
                self.on_log(f"组合模式：已确认 {label}。")
                return True
            if detection.state == STATE_CONTROLLER_DISCONNECTED:
                self.on_log("组合模式：检测到控制器未连接弹窗，按 A 恢复。")
                if not self._tap(pad or self.pad_provider(), "a", after=1.0):
                    return False
            elif detection.state == STATE_CONFIRM_MODAL:
                self.on_log("组合模式：遇到确认弹窗，按 A 继续。")
                if not self._tap(pad or self.pad_provider(), "a", after=1.0):
                    return False
            if not self._sleep(0.6):
                return False
        return False

    def _wait_for_prestart(self, pad, auto_focus, require_foreground):
        deadline = time.monotonic() + 18.0
        tapped_again = False
        while time.monotonic() < deadline and not self._stop.is_set():
            if not self._ensure_foreground(auto_focus, require_foreground):
                return False
            try:
                smart_detection = self.smart_runner.detect_once()
            except Exception as exc:
                self.logger.warning("Combo prestart smart detection failed: %s", exc)
                smart_detection = None
            if smart_detection and smart_detection.state in (STATE_PRESTART, STATE_PRESTART_WRONG_SELECTION):
                self.on_log("组合模式：已识别到 EventLab 开始赛事菜单。")
                return True

            buy_detection = self._detect_buy(auto_focus, require_foreground)
            if buy_detection and buy_detection.state == STATE_CONTROLLER_DISCONNECTED:
                self.on_log("组合模式：控制器弹窗，按 A 恢复。")
                if not self._tap(pad, "a", after=1.0):
                    return False
            elif buy_detection and buy_detection.state in (STATE_EVENTLAB_EVENTS, STATE_EVENTLAB_FAVORITES) and not tapped_again:
                self.on_log("组合模式：仍在 EventLab 列表，补按一次 A 进入当前收藏赛事。")
                tapped_again = True
                if not self._tap(pad, "a", after=2.0):
                    return False
            if not self._sleep(0.8):
                return False
        return False

    def _detect_buy(self, auto_focus, require_foreground):
        if not self._ensure_foreground(auto_focus, require_foreground):
            return None
        try:
            return self.buy_runner.detect_once()
        except Exception as exc:
            self.logger.warning("Combo buy-state detection failed: %s", exc)
            self.on_log(f"组合模式截图识别失败：{exc}")
            return None
