from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading
import time

import config
import focus
from buy_car_runner import BuyCarRunner
from gamepad import Gamepad
from screen_detector import STATE_CONTROLLER_DISCONNECTED, STATE_PRESTART, STATE_PRESTART_WRONG_SELECTION, STATE_RACING
from smart_runner import SmartRunner
from v3.buying_ui import normalize_text
from v3.frame_utils import save_frame_png, timestamp_slug
from v4.decision import (
    BUY_FLOW_CHILD_SCREENS,
    RouteContext,
    V4Decision,
    decide_mode3_navigation,
    normalize_button,
    progress_token,
)
from v4.farm_runner import VisionFarmRunner
from v4.recognizer import V4Recognizer, V4Snapshot
from v4.watchdog import ProgressWatchdog
from window_capture import capture_client


@dataclass
class V4StepRecord:
    index: int
    phase: str
    screen: str
    active_tab: str
    selected_item: str
    decision: str
    button: str = ""
    confidence: float = 0.0
    note: str = ""
    elapsed_ms: float = 0.0


@dataclass
class V4RunReport:
    started_at: str
    title: str
    finished_at: str = ""
    mode: str = "v4_mode3"
    completed: bool = False
    stopped_reason: str = ""
    steps: list[V4StepRecord] = field(default_factory=list)
    reports: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class V4Mode3Runner:
    """Vision-guided V4 runner for V1 mode 3.

    V4 keeps V1's proven buy/farm subrunners, but replaces the fragile
    EventLab transition with V3 semantic recognition and a 120s progress
    watchdog.  It only sends normal virtual Xbox controller inputs.
    """

    def __init__(
        self,
        title: str = "Forza",
        model_path: str | None = None,
        min_confidence: float = 0.42,
        watchdog_seconds: float = 120.0,
        report_dir: str | Path = "reports",
        on_log=None,
        logger=None,
        pad_provider=None,
    ):
        self.title = title
        self.report_dir = Path(report_dir)
        self.on_log = on_log or (lambda message: None)
        self.logger = logger or logging.getLogger("forza6helper.v4")
        self.recognizer = V4Recognizer(
            title=title,
            model_path=model_path,
            min_confidence=min_confidence,
            logger=self.logger,
        )
        self.watchdog_seconds = float(watchdog_seconds)
        self._external_pad_provider = pad_provider
        self._pad: Gamepad | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.buy_runner = BuyCarRunner(on_log=self.on_log, logger=self.logger, pad_provider=self._pad_provider)
        self.smart_runner = SmartRunner(on_log=self.on_log, logger=self.logger, pad_provider=self._pad_provider)
        self.vision_farm_runner = VisionFarmRunner(
            title=title,
            recognizer=self.recognizer,
            on_log=self.on_log,
            logger=self.logger,
            pad_provider=self._pad_provider,
            stall_seconds=self.watchdog_seconds,
        )
        self._farm_mode = "vision"
        self.nav_mode = "v4"  # default: proven full-path V4 nav. "v5" = faster event-driven
        # auto-nav, but it can short-circuit to a false race_menu (skip EventLab) -> opt-in only.
        self.report = V4RunReport(datetime.now(timezone.utc).astimezone().isoformat(), title)
        self._step_index = 0

    def _pad_provider(self):
        if self._external_pad_provider is not None:
            return self._external_pad_provider()
        if self._pad is None:
            self._pad = Gamepad(logger=self.logger)
        return self._pad

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(
        self,
        startup_delay: float = 0.0,
        farm_seconds: float | None = None,
        run_buy: bool = True,
        run_farm: bool = True,
        exit_after_farm: bool = True,
        auto_focus: bool = False,
        require_foreground: bool = True,
        loop_rounds: int = 1,
        max_consecutive_failures: int = 3,
    ) -> None:
        if self.is_running():
            self._log("V4 已在运行，忽略重复启动。")
            return
        self._stop.clear()
        use_loop = self._loop_rounds(loop_rounds) != 1
        target = self.run_loop if use_loop else self.run_once
        self._thread = threading.Thread(
            target=target,
            kwargs={
                "startup_delay": startup_delay,
                "farm_seconds": farm_seconds,
                "run_buy": run_buy,
                "run_farm": run_farm,
                "exit_after_farm": exit_after_farm,
                "auto_focus": auto_focus,
                "require_foreground": require_foreground,
                **({"loop_rounds": loop_rounds, "max_consecutive_failures": max_consecutive_failures} if use_loop else {}),
            },
            name="v4-mode3-runner",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.buy_runner.stop()
        self.smart_runner.stop()
        self.vision_farm_runner.stop()
        if self._pad:
            self._pad.neutral()

    def detect_once(self) -> V4Snapshot:
        return self.recognizer.capture(full_ocr=True, region_ocr=True)

    def run_once(
        self,
        startup_delay: float = 0.0,
        farm_seconds: float | None = None,
        run_buy: bool = True,
        run_farm: bool = True,
        exit_after_farm: bool = True,
        auto_focus: bool = False,
        require_foreground: bool = True,
    ) -> bool:
        self.report = V4RunReport(datetime.now(timezone.utc).astimezone().isoformat(), self.title)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        pad = None
        try:
            pad = self._pad_provider()
            pad.neutral()
            if startup_delay > 0:
                self._log(f"V4 将在 {startup_delay:.0f} 秒后开始模式三。")
                if not self._sleep(startup_delay):
                    return False

            if not self._ensure_foreground(auto_focus, require_foreground):
                return self._finish(False, "game_not_foreground")

            if run_buy:
                if not self._run_buy_phase(auto_focus=auto_focus, require_foreground=require_foreground):
                    return self._finish(False, "buy_phase_failed")
            else:
                self._log("V4 跳过买车阶段，从当前页面续接 EventLab 导航。")

            if not self._navigate(pad, auto_focus, require_foreground):
                return self._finish(False, "eventlab_navigation_failed")

            if run_farm:
                seconds = self._farm_seconds(farm_seconds)
                if not self._run_farm_phase(seconds, auto_focus=auto_focus, require_foreground=require_foreground):
                    return self._finish(False, "farm_phase_failed")
                if exit_after_farm and not self._exit_after_farm(pad, auto_focus, require_foreground):
                    return self._finish(False, "exit_after_farm_failed")
            else:
                self._log("V4 已到达 EventLab 开始赛事菜单；本次按配置不启动刷分阶段。")

            return self._finish(True, "completed")
        except Exception as exc:
            self.logger.exception("V4 mode3 crashed")
            self.report.errors.append(str(exc))
            return self._finish(False, f"exception: {exc}")
        finally:
            if pad:
                pad.neutral()
            self.write_report()

    def run_loop(
        self,
        startup_delay: float = 0.0,
        farm_seconds: float | None = None,
        run_buy: bool = True,
        run_farm: bool = True,
        exit_after_farm: bool = True,
        auto_focus: bool = False,
        require_foreground: bool = True,
        loop_rounds: int = 0,
        max_consecutive_failures: int = 3,
    ) -> bool:
        rounds = self._loop_rounds(loop_rounds)
        round_label = "无限" if rounds is None else str(rounds)
        if not run_farm:
            self._log("V4 完整循环需要刷图阶段；当前跳过刷图，所以只跑一轮。")
            return self.run_once(
                startup_delay=startup_delay,
                farm_seconds=farm_seconds,
                run_buy=run_buy,
                run_farm=run_farm,
                exit_after_farm=exit_after_farm,
                auto_focus=auto_focus,
                require_foreground=require_foreground,
            )
        if not exit_after_farm:
            # A multi-round loop MUST return to a known page (the pause menu)
            # between rounds, otherwise the next round's buy phase has no clean
            # start point. Rather than silently degrading to a single round
            # (which surprised the user: loop_rounds=0 stopped after one round),
            # auto-enable the post-farm cleanup and keep looping.
            self._log(
                "V4 完整循环需要刷图后收尾才能回到买车起点；"
                "已自动开启“刷图结束后回收尾到暂停菜单”以支持连续循环。"
            )
            exit_after_farm = True
        if self._farm_seconds(farm_seconds) is None:
            self._log("V4 完整循环已启用，但刷图时间=0 表示本轮无限刷；外层不会进入下一轮，直到你停止或刷图器退出。")
        if not run_buy:
            self._log("V4 完整循环当前勾选了跳过买车；下一轮也不会重新买车/加点，只会从当前状态续接导航。")

        completed_rounds = 0
        consecutive_failures = 0
        max_failures = max(1, int(max_consecutive_failures))
        attempt_no = 0
        while rounds is None or completed_rounds < rounds:
            if self._stop.is_set():
                self._log("V4 完整循环收到停止请求，结束外层循环。")
                return completed_rounds > 0
            attempt_no += 1
            self._log(
                f"V4 完整模式三循环：第 {completed_rounds + 1}/{round_label} 轮开始"
                f"(本轮第 {attempt_no} 次尝试)。"
            )
            ok = self.run_once(
                startup_delay=startup_delay if attempt_no == 1 else 0.0,
                farm_seconds=farm_seconds,
                run_buy=run_buy,
                run_farm=run_farm,
                exit_after_farm=exit_after_farm,
                auto_focus=auto_focus,
                require_foreground=require_foreground,
            )
            reason = self.report.stopped_reason
            self._log(f"V4 完整模式三循环：本轮结束，结果={reason}，ok={ok}。")
            if self._stop.is_set():
                return completed_rounds > 0
            if not ok:
                consecutive_failures += 1
                self._log(
                    f"V4 完整循环：本轮失败({reason})，连续失败 {consecutive_failures}/{max_failures}。"
                )
                if consecutive_failures >= max_failures:
                    self._log(f"V4 完整循环：连续失败 {max_failures} 次,停止外层循环等待人工检查。")
                    return completed_rounds > 0
                pad = self._pad_provider()
                if not self._recover_between_rounds(pad):
                    self._log("V4 完整循环：退回安全菜单失败,停止外层循环。")
                    return completed_rounds > 0
                if not self._sleep(3.0):
                    return completed_rounds > 0
                continue
            consecutive_failures = 0
            completed_rounds += 1
            if rounds is not None and completed_rounds >= rounds:
                break
            if not self._sleep(3.0):
                return completed_rounds > 0

        self._log(f"V4 完整模式三循环完成：共 {completed_rounds} 轮。")
        return completed_rounds > 0

    def _recover_between_rounds(self, pad) -> bool:
        """After a failed round, gently back out to a safe menu using only B /
        Menu (and A only for the controller modal) so the next round can start.

        It never blind-presses A on grids/cards -- that is exactly what risks a
        mis-buy or a Photo-Mode-style mis-trigger. B backs out one level
        everywhere; Menu opens the pause menu from free roam.
        """
        self._log("V4 循环恢复：用 B/Menu 退回暂停/自由漫游,准备重开下一轮。")
        safe = {"free_roam_hud", "idle_showcase", "race_menu", "pause_menu"}
        for _attempt in range(1, 9):
            if self._stop.is_set():
                return False
            try:
                snapshot = self._recognize()
            except Exception:
                if not self._sleep(0.8):
                    return False
                continue
            screen = str(snapshot.v3.screen)
            if screen.startswith("pause_") or screen in safe:
                self._log(f"V4 循环恢复：已回到 {screen},可以重开下一轮。")
                return True
            if screen == "controller_disconnected":
                if not self._tap(pad, "a", after=1.0):
                    return False
                continue
            if screen == "free_roam_hud":
                if not self._tap(pad, "start", after=1.2):
                    return False
                continue
            if screen == "loading_transition":
                if not self._sleep(1.0):
                    return False
                continue
            if not self._tap(pad, "b", after=1.2):
                return False
        if not self._tap(pad, "start", after=1.4):
            return False
        screen = str(self._recognize().v3.screen)
        return screen.startswith("pause_") or screen in safe

    def _run_buy_phase(self, auto_focus: bool, require_foreground: bool) -> bool:
        self._log("V4 买车/加点阶段交给 V1 BuyCarRunner；结束条件仍是技术点数不足弹窗。")
        phase = "buy_phase"
        watchdog = ProgressWatchdog(timeout_seconds=self.watchdog_seconds, max_recoveries=0)
        monitor_interval = self._child_watchdog_interval()
        next_monitor = 0.0
        started = time.monotonic()
        buy_recoveries = 0
        monitor_decision = V4Decision(
            "monitor_buy_phase",
            "",
            "V4 is supervising the V1 BuyCarRunner with semantic screenshots.",
            "If the page/focus token does not change within the watchdog window, V4 stops BuyCarRunner and writes an attention report.",
            0.0,
        )
        try:
            preflight_context = RouteContext()
            preflight = None
            preflight_decision = monitor_decision
            for attempt in range(1, 6):
                preflight = self._recognize()
                preflight_decision = self._decide(preflight, preflight_context)
                note = "preflight" if attempt == 1 else f"preflight_after_controller={attempt - 1}"
                record_decision = preflight_decision if preflight_decision.name == "dismiss_controller_modal" else monitor_decision
                self._record_step(phase, preflight, record_decision, note=note)
                if self._buy_phase_can_handoff_to_v4(preflight):
                    self._log(
                        "V4 buy preflight sees an EventLab/race route page; "
                        "skipping BuyCarRunner and handing off to V4 navigation."
                    )
                    return True
                if preflight_decision.name in {"confirm_restart_event"}:
                    self._log(
                        "V4 buy preflight sees an EventLab restart confirmation modal; "
                        "skipping BuyCarRunner and handing off to V4 navigation."
                    )
                    return True
                if preflight_decision.name not in {
                    "dismiss_controller_modal",
                    "back_out_from_buy_flow",
                    "open_pause_from_world",
                }:
                    break
                pad = self._pad_provider()
                if not self._execute_decision(pad, preflight_decision, preflight_context):
                    return False
            if preflight_decision.name == "dismiss_controller_modal":
                self.report.errors.append("buy_phase_controller_modal_not_cleared")
                self._log("V4 buy preflight still sees controller-disconnected modal; not starting BuyCarRunner.")
                return False
            if preflight is not None and self._buy_phase_needs_driving_disambiguation(preflight):
                pad = self._pad_provider()
                self._log(
                    "V4 buy preflight sees a driving/racing-like HUD; "
                    "opening the pause menu once to distinguish free roam from an active race."
                )
                if not self._tap(pad, "start", after=1.6):
                    return False
                preflight = self._recognize()
                self._record_step(phase, preflight, monitor_decision, button="start", note="preflight_driving_disambiguation")
                if self._buy_phase_can_handoff_to_v4(preflight):
                    self._log(
                        "V4 buy preflight confirmed an EventLab/race route page after Menu; "
                        "skipping BuyCarRunner and handing off to V4 navigation."
                    )
                    return True
        except Exception as exc:
            self.report.errors.append(f"buy_phase_preflight_failed: {exc}")
            self.logger.warning("V4 buy phase preflight failed: %s", exc)
        self.buy_runner.start(
            startup_delay=0.0,
            total_seconds=None,
            auto_focus=auto_focus,
            require_foreground=require_foreground,
        )
        handoff_streak = 0
        while self.buy_runner.is_running() and not self._stop.is_set():
            now = time.monotonic()
            if now >= next_monitor:
                next_monitor = now + monitor_interval
                try:
                    snapshot = self._recognize_buy_monitor()
                    token = progress_token(snapshot.v3, extra=f"buy:{self.buy_runner.stop_reason or ''}")
                    changed = watchdog.observe(phase, token)
                    self._record_step(
                        phase,
                        snapshot,
                        monitor_decision,
                        note="progress" if changed else f"stable_for={watchdog.elapsed_without_progress():.1f}s",
                    )
                    if self._buy_phase_can_handoff_to_v4(snapshot):
                        # Debounce: a single car-grid frame can still mis-read as
                        # eventlab_my_cars (same card-grid shape) and would abort the
                        # purchase mid-way, leaving skill points unspent. Require TWO
                        # consecutive monitor checks on an EventLab/race page before
                        # handing off -- a genuine wander into EventLab persists, a
                        # one-frame misread does not.
                        handoff_streak += 1
                        if handoff_streak >= 2:
                            self._log(
                                "V4 buy monitor sees an EventLab route page on 2 "
                                "consecutive checks; stopping BuyCarRunner and handing "
                                "off to V3/V4 navigation."
                            )
                            self.buy_runner.stop()
                            self._join_buy_runner(timeout=5.0)
                            return True
                        self._log(
                            f"V4 买车监控偶见疑似 EventLab 页({snapshot.v3.screen})；"
                            "车卡网格可能被误判，先不交接，下一次再确认。"
                        )
                        if not self._sleep(0.25):
                            break
                        continue
                    handoff_streak = 0
                    if (
                        str(snapshot.v3.screen) == "world_map"
                        and watchdog.elapsed_without_progress() >= self._buy_recovery_seconds()
                        and buy_recoveries < 1
                    ):
                        buy_recoveries += 1
                        self._log("V4 buy watchdog sees a stable world_map; closing map with B and restarting BuyCarRunner once.")
                        self.buy_runner.stop()
                        self._join_buy_runner(timeout=5.0)
                        pad = self._pad_provider()
                        if not self._tap(pad, "b", after=1.5):
                            return False
                        self.buy_runner.start(
                            startup_delay=0.0,
                            total_seconds=None,
                            auto_focus=auto_focus,
                            require_foreground=require_foreground,
                        )
                        watchdog.reset(phase, f"buy:world_map_recovery:{buy_recoveries}")
                        next_monitor = time.monotonic() + monitor_interval
                        continue
                    if (
                        str(snapshot.v3.screen) in {
                            "idle_showcase",
                            "unknown",
                            "loading_transition",
                            "autoshow_buy_sell",
                            "autoshow_showroom",
                            "garage_my_cars",
                            "post_purchase_view",
                        }
                        and watchdog.elapsed_without_progress() >= self._buy_recovery_seconds()
                        and buy_recoveries < 3
                    ):
                        buy_recoveries += 1
                        self._log(
                            "V4 buy watchdog sees a stale buy/idle context; "
                            f"probing A/B/Menu before restarting BuyCarRunner ({buy_recoveries}/3)."
                        )
                        self.buy_runner.stop()
                        self._join_buy_runner(timeout=5.0)
                        pad = self._pad_provider()
                        before = progress_token(snapshot.v3)
                        for button in ("a", "b", "start"):
                            if not self._tap(pad, button, after=1.4):
                                return False
                            recovered = self._recognize_buy_monitor()
                            self._record_step(
                                phase,
                                recovered,
                                monitor_decision,
                                button=button,
                                note=f"buy_context_probe={buy_recoveries}",
                            )
                            if self._buy_phase_can_handoff_to_v4(recovered):
                                return True
                            recovered_screen = str(recovered.v3.screen)
                            if recovered_screen not in {"idle_showcase", "unknown", "loading_transition"}:
                                break
                            if progress_token(recovered.v3) != before:
                                before = progress_token(recovered.v3)
                        self.buy_runner.start(
                            startup_delay=0.0,
                            total_seconds=None,
                            auto_focus=auto_focus,
                            require_foreground=require_foreground,
                        )
                        watchdog.reset(phase, f"buy:context_recovery:{buy_recoveries}")
                        next_monitor = time.monotonic() + monitor_interval
                        continue
                    if watchdog.stalled():
                        reason = (
                            f"buy_phase_watchdog_stop after {time.monotonic() - started:.1f}s "
                            f"(no semantic progress for {watchdog.elapsed_without_progress():.1f}s)"
                        )
                        self.report.errors.append(reason)
                        report_path = self._write_attention_report(snapshot, monitor_decision, phase, 1)
                        self._log(f"V4 buy watchdog stopped BuyCarRunner; attention report: {report_path}")
                        self.buy_runner.stop()
                        self._join_buy_runner(timeout=5.0)
                        return False
                except Exception as exc:
                    self.report.errors.append(f"buy_phase_monitor_failed: {exc}")
                    self.logger.warning("V4 buy phase monitor failed: %s", exc)
            if not self._sleep(0.25):
                break
        if self._stop.is_set():
            return False
        if self.buy_runner.stop_reason != "points_exhausted":
            self._log(f"V4 买车阶段停止原因不是 points_exhausted：{self.buy_runner.stop_reason or 'unknown'}。")
            return False
        self._log("V4 已确认买车阶段到达技术点数不足，开始 V3 视觉导航去 EventLab。")
        return True

    def _navigate(self, pad, auto_focus: bool, require_foreground: bool) -> bool:
        if self.nav_mode == "v5":
            return self._navigate_via_v5(pad, auto_focus, require_foreground)
        return self._navigate_to_eventlab_prestart(pad, auto_focus, require_foreground)

    def _navigate_via_v5(self, pad, auto_focus: bool, require_foreground: bool) -> bool:
        """Event-driven navigation via the V5 reactor, sharing this runner's
        recognizer + pad. Buy/farm stay on the proven V4 path; only the nav phase
        is V5 (no fixed settle sleeps). True when it reaches the start-race menu."""
        from v5.nav_runner import V5Navigator

        self._log("V4 导航阶段：改用 V5 事件驱动导航（共用识别器与手柄，去掉固定等待）。")
        nav = V5Navigator(
            title=self.title, goal="race_menu",
            recognizer=self.recognizer, pad=pad, engine=None, use_capture_engine=False,
            auto_focus=auto_focus, require_foreground=require_foreground,
            on_log=self.on_log, logger=self.logger,
            stall_seconds=self.watchdog_seconds, max_seconds=18 * 60,
        )
        return nav.run().reason == "goal"

    def _navigate_to_eventlab_prestart(self, pad, auto_focus: bool, require_foreground: bool) -> bool:
        context = RouteContext()
        watchdog = ProgressWatchdog(timeout_seconds=self.watchdog_seconds, max_recoveries=3)
        phase = "eventlab_navigation"
        max_route_seconds = 18 * 60
        started = time.monotonic()
        self._log("V4 EventLab 导航启动：每次只按一个键，然后重新识别验证。")

        arrived_streak = 0
        while not self._stop.is_set() and time.monotonic() - started <= max_route_seconds:
            if not self._ensure_foreground(auto_focus, require_foreground):
                return False
            snapshot = self._recognize()
            self._update_context_from_snapshot(context, snapshot)
            smart_ready = self._smart_state_confirms_eventlab(snapshot)
            decision = self._decide(snapshot, context)
            token = progress_token(snapshot.v3, extra=f"{decision.name}:{context.favorite_filter_done}")
            changed = watchdog.observe(phase, token)
            self._record_step(phase, snapshot, decision, note="progress" if changed else "")

            if smart_ready or decision.terminal:
                # Debounce: at lower resolution V3 can mis-read free roam (the
                # festival start line) as race_hud, and V1 smart mis-reads it as
                # RACING -- a one-frame false "arrived" hands the farm an idle car
                # in free roam (it then holds throttle). Require TWO consecutive
                # arrival frames; a real start menu / race persists, a misread does
                # not.
                arrived_streak += 1
                if arrived_streak >= 2:
                    self._log("V4 已确认到达 EventLab 开始赛事菜单（连续 2 帧确认）。")
                    return True
                self._log(
                    f"V4 疑似到达开始赛事菜单（screen={snapshot.v3.screen}，"
                    f"smart={snapshot.smart_state}）；再确认一帧，防止自由漫游被误判成比赛。"
                )
                if not self._sleep(0.6):
                    return False
                continue
            arrived_streak = 0

            if watchdog.stalled():
                if not self._recover_stall(pad, snapshot, decision, watchdog, phase):
                    return False
                continue

            if not decision.can_press:
                self._log(f"V4 等待/不按键：{decision.name}；{decision.reason}")
                if not self._sleep(0.85):
                    return False
                continue

            if not self._execute_decision(pad, decision, context):
                return False
            # Wait for the screen to settle (cheap frame-diff) before the next ~0.7s OCR,
            # instead of wasting recognitions on mid-transition frames. Accuracy-safe.
            self._settle_after_press()

        self._log("V4 EventLab 导航超过最大时长，已停止，避免继续盲按。")
        return False

    def _run_farm_phase(self, farm_seconds: float | None, auto_focus: bool, require_foreground: bool) -> bool:
        if self._farm_mode == "smart":
            runner, label = self.smart_runner, "V1 SmartRunner"
        else:
            runner, label = self.vision_farm_runner, "V3 视觉刷图 VisionFarmRunner"
        if farm_seconds is None:
            self._log(f"V4 已到开始赛事菜单，交给 {label} 持续跑模式一；直到手动停止或刷图器看门狗触发。")
        else:
            self._log(f"V4 已到开始赛事菜单，交给 {label} 跑模式一约 {farm_seconds / 60:.1f} 分钟。")
        started = time.monotonic()
        farm_watchdog_seconds = self._farm_watchdog_seconds()
        farm_deadline_logged = False
        runner.start(
            startup_delay=0.0,
            total_seconds=farm_seconds,
            auto_focus=auto_focus,
            require_foreground=require_foreground,
        )
        while runner.is_running() and not self._stop.is_set():
            elapsed = time.monotonic() - started
            if farm_seconds is None:
                if not self._sleep(0.25):
                    break
                continue
            if elapsed >= farm_seconds and not farm_deadline_logged:
                farm_deadline_logged = True
                self._log(
                    "V4 刷分目标时长已到，等待刷图器平滑退出；"
                    f"最多再等 {farm_watchdog_seconds:.0f} 秒。"
                )
            if elapsed >= farm_seconds + farm_watchdog_seconds:
                reason = (
                    f"farm_watchdog_stop after {elapsed:.1f}s "
                    f"(target={farm_seconds:.1f}s, farm_reason={runner.exit_reason or 'unknown'})"
                )
                self.report.errors.append(reason)
                self._log(
                    "V4 farm 看门狗触发：刷图器超过目标时长后仍未退出，"
                    "已强制停止并把控制权交回 V4。"
                )
                runner.stop()
                self._join_runner(runner, timeout=5.0)
                break
            if not self._sleep(0.25):
                break
        if self._stop.is_set():
            return False
        self._log(f"V4 刷分阶段结束：{runner.exit_reason or 'unknown'}。")
        return True

    def _exit_after_farm(self, pad, auto_focus: bool, require_foreground: bool) -> bool:
        self._log("V4 尝试从赛后/自由漫游回到暂停菜单，为下一轮模式三收尾。")
        watchdog = ProgressWatchdog(timeout_seconds=self.watchdog_seconds, max_recoveries=2)
        phase = "exit_after_farm"
        unknown_streak = 0
        for attempt in range(1, 16):
            if not self._ensure_foreground(auto_focus, require_foreground):
                return False
            snapshot = self._recognize()
            decision = self._decide(snapshot, RouteContext())
            token = progress_token(snapshot.v3, extra=f"exit:{attempt}")
            watchdog.observe(phase, token)
            self._record_step(phase, snapshot, decision, note=f"exit_attempt={attempt}")
            screen = snapshot.v3.screen
            if str(screen).startswith("pause_") or screen in ("pause_menu", "race_menu", "race_pause_menu"):
                self._log("V4 已回到可安全交还的菜单。")
                return True
            if screen == "unknown":
                # Don't press B on a single mid-transition mis-read: backing out of a menu we
                # only momentarily mis-read as unknown is the likely cause of the 收尾 loop.
                # Wait + re-read; only fall through to a last-resort B once unknown persists.
                unknown_streak += 1
                if unknown_streak < 3:
                    if not self._sleep(0.5):
                        return False
                    continue
                unknown_streak = 0
            else:
                unknown_streak = 0
            if screen == "race_result":
                # Post-race results/standings: advance with A (B does not leave
                # this page) toward post_race_next / free roam.
                if not self._tap(pad, "a", after=1.8):
                    return False
                continue
            if screen == "post_race_next":
                if not self._tap(pad, "b", after=2.0):
                    return False
                continue
            if screen in ("free_roam_hud", "idle_showcase"):
                if not self._tap(pad, "start", after=1.5):
                    return False
                continue
            if screen == "controller_disconnected":
                if not self._tap(pad, "a", after=1.0):
                    return False
                continue
            if screen == "loading_transition":
                if not self._sleep(1.0):
                    return False
                continue
            if not self._tap(pad, "b", after=1.4):
                return False
        self._log("V4 未能确认回到暂停菜单，停止收尾。")
        return False

    def _execute_decision(self, pad, decision: V4Decision, context: RouteContext) -> bool:
        button = normalize_button(decision.button)
        if not button:
            return True
        self._log(f"V4 按键：{decision.button} -> {button}；{decision.name}。验证：{decision.verify}")
        if decision.name == "move_creative_focus_to_eventlab":
            context.creative_focus_moves += 1
        elif decision.name == "scan_favorite_event_cards":
            context.eventlab_card_moves += 1
        elif decision.name == "scan_filtered_vehicle_cards":
            context.vehicle_card_moves += 1
        elif decision.name == "return_from_checked_filter":
            context.favorite_filter_done = True
            context.favorite_filter_checked = True
        elif decision.name == "close_locked_feature_modal":
            context.locked_feature_seen = True
        elif decision.name == "back_out_after_locked_feature":
            context.locked_backouts += 1
        return self._tap(pad, button, after=self._settle_for_decision(decision))

    def _decide(self, snapshot: V4Snapshot, context: RouteContext) -> V4Decision:
        selected_norm = normalize_text(getattr(snapshot.v3, "selected_item", "") or "")
        if snapshot.v3.screen == "modal_warning" and any(token in selected_norm for token in ("请稍候", "PLEASEWAIT", "LOADING")):
            return V4Decision(
                "wait_modal_loading",
                "",
                "弹窗/遮罩文字是请稍候，按键不能加速，等待下一帧。",
                "必须重新识别到 eventlab_my_cars、race_menu、controller_disconnected 或明确弹窗后再操作。",
                max(float(snapshot.v3.confidence), 0.70),
            )
        controller_text = any(token in selected_norm for token in ("控制器", "CONTROLLER", "重新连接"))
        if snapshot.smart_state == STATE_CONTROLLER_DISCONNECTED and (
            snapshot.v3.screen == "controller_disconnected"
            or controller_text
            or snapshot.v3.screen in ("unknown", "idle_showcase", "loading_transition")
        ):
            return V4Decision(
                "dismiss_controller_modal",
                "A",
                "V1 race detector sees the controller-disconnected modal; press A once to reconnect/confirm.",
                "按后必须重新识别，不再显示 controller_disconnected。",
                max(float(snapshot.smart_confidence), 0.76),
            )
        # V4 robustness rule: trust V3 vision -- not V1's fixed-fraction detector --
        # for "we have arrived at the race". If V1 smart says RACING but V3 does NOT
        # see a real race_hud (it sees free roam / idle / unknown), it is the
        # festival start line mis-read as racing. Do NOT hand off to the farm; open
        # the pause menu and keep navigating to EventLab.
        if snapshot.smart_state == STATE_RACING and snapshot.v3.screen in (
            "unknown",
            "idle_showcase",
            "free_roam_hud",
        ):
            return V4Decision(
                "open_pause_from_world",
                "Menu",
                "V1 误判为比赛中,但 V3 没看到真正的 race_hud,多半是自由漫游(嘉年华起跑线)被误读;"
                "按 Menu 打开暂停菜单继续导航,不交给刷图。",
                "按后必须重新识别到 pause_* 或 pause_menu;未变化则不连续盲按。",
                max(float(snapshot.v3.confidence), 0.58),
            )
        if self._smart_state_confirms_eventlab(snapshot):
            return V4Decision(
                "arrived_race_hud" if snapshot.smart_state == STATE_RACING else "arrived_race_menu",
                "",
                "V1 race detector has confirmed the EventLab pre-start menu or race HUD.",
                "交给 SmartRunner 前必须保持开始赛事菜单或比赛 HUD 可见。",
                max(float(snapshot.smart_confidence), 0.80),
                terminal=True,
            )
        return decide_mode3_navigation(snapshot.v3, context)

    def _recover_stall(
        self,
        pad,
        snapshot: V4Snapshot,
        decision: V4Decision,
        watchdog: ProgressWatchdog,
        phase: str,
    ) -> bool:
        recovery_index = watchdog.note_recovery()
        report_path = self._write_attention_report(snapshot, decision, phase, recovery_index)
        self._log(
            f"V4 {self.watchdog_seconds:.0f} 秒没有语义进展，已写入 {report_path}，开始有限恢复 {recovery_index}/3。"
        )
        if not watchdog.can_recover():
            self._log("V4 恢复次数用尽，停止并等待接手。")
            return False

        screen = snapshot.v3.screen
        if decision.can_press and decision.name not in {"modal_needs_text", "target_event_not_found", "target_vehicle_not_found"}:
            return self._execute_decision(pad, decision, RouteContext())

        probes: list[str]
        if screen == "loading_transition":
            return self._sleep(2.0)
        if screen in ("idle_showcase", "unknown"):
            probes = ["a", "b", "start"]
        elif screen in ("free_roam_hud",):
            probes = ["start"]
        elif screen == "controller_disconnected":
            probes = ["a"]
        elif screen == "post_race_next":
            probes = ["b"]
        else:
            probes = []

        if not probes:
            self._log(f"V4 对 {screen} 没有安全恢复键，停止避免误操作。")
            return False

        before = progress_token(snapshot.v3)
        for button in probes:
            if not self._tap(pad, button, after=1.2):
                return False
            after = self._recognize()
            self._record_step(phase, after, decision, button=button, note="stall_probe")
            if progress_token(after.v3) != before:
                watchdog.reset(phase, progress_token(after.v3))
                return True
        return True

    def _update_context_from_snapshot(self, context: RouteContext, snapshot: V4Snapshot) -> None:
        v3 = snapshot.v3
        filter_state = getattr(v3, "filter_state", {}) or {}
        if v3.screen == "eventlab_filter" and filter_state.get("favorite_checked") is True:
            context.favorite_filter_checked = True
        if v3.screen == "eventlab_my_cars" and context.favorite_filter_checked:
            context.favorite_filter_done = True

    def _recognize(self, full_ocr: bool = True, region_ocr: bool = True) -> V4Snapshot:
        snapshot = self.recognizer.capture(full_ocr=full_ocr, region_ocr=region_ocr)
        self.logger.info(
            "V4 recognize full_ocr=%s region_ocr=%s screen=%s tab=%s selected=%s conf=%.2f smart=%s elapsed=%.1fms",
            full_ocr,
            region_ocr,
            snapshot.v3.screen,
            snapshot.v3.active_tab,
            snapshot.v3.selected_item,
            snapshot.v3.confidence,
            snapshot.smart_state,
            snapshot.elapsed_ms,
        )
        return snapshot

    def _settle_after_press(self, cap: float = 1.2) -> None:
        """After a nav key-press, wait CHEAPLY (downscaled-grayscale frame-diff, no OCR) until
        the screen has changed and then settled, before the NEXT full recognition. This skips
        wasting ~0.7s OCR on mid-transition/loading frames -- the main nav speed-up.

        Accuracy-safe by construction: it never changes WHAT gets recognised, only WHEN. Worst
        case (thresholds off / animated screen) it just waits the cap = today's behaviour, and
        the existing loading_transition handling is the backstop. Reuses the frame-diff helpers
        validated for the buy phase."""
        floor, poll = 0.12, 0.04
        if not self._sleep(floor):
            return
        try:
            hwnd = focus.find_window(self.title)
            if not hwnd:
                return
            pre = BuyCarRunner._small_gray(capture_client(hwnd))
            last, changed, stable = pre, False, 0
            end = time.monotonic() + max(0.0, cap - floor)
            while time.monotonic() < end:
                if self._stop.is_set():
                    return
                time.sleep(poll)
                cur = BuyCarRunner._small_gray(capture_client(hwnd))
                if cur is None:
                    continue
                if BuyCarRunner._frame_diff(pre, cur) > 6.0:
                    changed = True
                if changed and BuyCarRunner._frame_diff(last, cur) <= 2.0:
                    stable += 1
                    if stable >= 2:
                        return
                else:
                    stable = 0
                last = cur
        except Exception:
            return

    def _recognize_buy_monitor(self) -> V4Snapshot:
        """Semantic heartbeat while V1 BuyCarRunner does the actual buying.

        This MUST use full OCR. The dense car grids (制造商列表 / 斯巴鲁车展 /
        购买车辆页) are visually almost identical to the EventLab car/events grid,
        so a detector/rules-only frame routinely mislabels them as an
        ``eventlab_my_cars`` / ``eventlab_events`` page (they share the same
        card-grid structure -- see ``v3/hybrid.py``). The monitor then thinks
        BuyCarRunner wandered into EventLab and aborts the purchase mid-flow, so
        the car never gets bought. Full OCR reads 购买车辆/制造商/斯巴鲁/车展 and
        classifies these as buy-flow screens (``vehicle_buy_grid`` /
        ``manufacturer_grid``), which are in ``_buy_phase_owned_screens`` and
        therefore never trigger a handoff; it also keeps the stall token honest
        as the highlighted car changes. The monitor only ticks every
        ``_child_watchdog_interval`` (watchdog/10, capped at 8s), so full OCR
        here is essentially free. The TypeError fallback preserves older
        unit-test monkeypatches that replace ``_recognize`` with a no-argument
        lambda.
        """
        try:
            return self._recognize(full_ocr=True, region_ocr=True)
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            return self._recognize()

    def _record_step(
        self,
        phase: str,
        snapshot: V4Snapshot,
        decision: V4Decision,
        button: str = "",
        note: str = "",
    ) -> None:
        self._step_index += 1
        self.report.steps.append(
            V4StepRecord(
                index=self._step_index,
                phase=phase,
                screen=str(snapshot.v3.screen),
                active_tab=str(snapshot.v3.active_tab),
                selected_item=str(snapshot.v3.selected_item),
                decision=decision.name,
                button=button or normalize_button(decision.button),
                confidence=float(snapshot.v3.confidence),
                note=note,
                elapsed_ms=float(snapshot.elapsed_ms),
            )
        )
        if len(self.report.steps) % 5 == 0:
            self.write_report()

    def _write_attention_report(
        self,
        snapshot: V4Snapshot,
        decision: V4Decision,
        phase: str,
        recovery_index: int,
    ) -> str:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        slug = timestamp_slug()
        png_path = self.report_dir / f"v4_attention_{slug}.png"
        json_path = self.report_dir / f"v4_attention_{slug}.json"
        try:
            save_frame_png(snapshot.frame, png_path)
        except Exception as exc:
            self.report.errors.append(f"save attention png failed: {exc}")
        payload = {
            "phase": phase,
            "recovery_index": recovery_index,
            "watchdog_seconds": self.watchdog_seconds,
            "decision": asdict(decision),
            "snapshot": snapshot.to_dict(),
            "image": str(png_path),
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        latest = self.report_dir / "v4_attention_latest.json"
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report.reports.append(str(json_path))
        self.write_report()
        return str(json_path)

    def _tap(self, pad, button: str, hold: float = 0.14, after: float = 0.8) -> bool:
        if self._stop.is_set():
            return False
        try:
            self.buy_runner._invalidate_ocr()
        except Exception:
            pass
        pad.tap(button, hold=hold)
        try:
            self.buy_runner._invalidate_ocr()
        except Exception:
            pass
        return self._sleep(after)

    def _sleep(self, seconds: float) -> bool:
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._stop.is_set():
                return False
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))
        return not self._stop.is_set()

    def _ensure_foreground(self, auto_focus: bool, require_foreground: bool) -> bool:
        if not require_foreground or focus.is_foreground(self.title):
            return True
        if auto_focus:
            self._log("V4 检测到游戏不在前台，尝试普通前台切换；不启用 KeepActive，也不发送 fake-focus 消息。")
            self._plain_activate_game()
            return self._sleep(0.5)
        self._log("V4 检测到游戏不在前台；按要求不 fake-focus，已暂停等待。")
        return False

    def _plain_activate_game(self) -> bool:
        hwnd = focus.find_window(self.title)
        if not hwnd or not focus.user32:
            return False
        try:
            focus.user32.ShowWindow(hwnd, focus.SW_RESTORE)
            focus.user32.BringWindowToTop(hwnd)
            focus.user32.SetForegroundWindow(hwnd)
            return True
        except Exception as exc:
            self.logger.warning("plain foreground activation failed: %s", exc)
            return False

    @staticmethod
    def _settle_for_decision(decision: V4Decision) -> float:
        if decision.name in {
            "enter_eventlab_from_creative_hub",
            "enter_eventlab_events",
            "select_target_event",
            "choose_single_player",
            "select_22b_for_eventlab",
        }:
            return 1.15
        if decision.name in {"open_pause_from_world", "open_vehicle_favorite_filter"}:
            return 0.85
        if decision.name == "dismiss_controller_modal":
            return 1.0
        return 0.55

    @staticmethod
    def _farm_seconds(override: float | None) -> float | None:
        if override is not None:
            if override > 0:
                return float(override)
            return None
        return float(getattr(config, "COMBO_EVENTLAB_FARM_SECONDS", 90 * 60))

    @staticmethod
    def _loop_rounds(value: int | float | None) -> int | None:
        if value is None:
            return 1
        rounds = int(value)
        if rounds <= 0:
            return None
        return rounds

    def _farm_watchdog_seconds(self) -> float:
        return max(0.0, float(self.watchdog_seconds))

    def _child_watchdog_interval(self) -> float:
        return max(0.25, min(8.0, float(self.watchdog_seconds) / 10.0))

    def _buy_recovery_seconds(self) -> float:
        return max(0.05, min(30.0, float(self.watchdog_seconds) / 4.0))

    def _buy_phase_can_handoff_to_v4(self, snapshot: V4Snapshot) -> bool:
        screen = str(getattr(snapshot.v3, "screen", "") or "")
        if screen in self._buy_phase_owned_screens():
            return False
        if self._smart_state_confirms_eventlab(snapshot, include_racing=False):
            return True
        if screen in {
            "eventlab_home",
            "eventlab_events",
            "eventlab_favorites",
            "eventlab_race_type",
            "eventlab_my_cars",
            "eventlab_filter",
            "race_menu",
            "prestart",
            "race_hud",
            "race_pause_menu",
        }:
            return True
        return False

    @staticmethod
    def _buy_phase_owned_screens() -> set[str]:
        return {
            "pause_vehicle_entry",
            "skill_points_exhausted",
        } | set(BUY_FLOW_CHILD_SCREENS)

    def _smart_state_confirms_eventlab(self, snapshot: V4Snapshot, include_racing: bool = True) -> bool:
        screen = str(getattr(snapshot.v3, "screen", "") or "")
        smart_state = str(getattr(snapshot, "smart_state", "") or "")
        if smart_state not in {STATE_PRESTART, STATE_PRESTART_WRONG_SELECTION, STATE_RACING}:
            return False
        if screen in self._buy_phase_owned_screens():
            return False
        selected = normalize_text(str(getattr(snapshot.v3, "selected_item", "") or ""))
        if smart_state in {STATE_PRESTART, STATE_PRESTART_WRONG_SELECTION}:
            if screen == "pause_story" and "开始" in selected and ("赛事" in selected or "竞赛" in selected):
                return True
        if screen.startswith("pause_") or screen in {"pause_menu", "modal_warning", "controller_disconnected"}:
            return False
        if smart_state in {STATE_PRESTART, STATE_PRESTART_WRONG_SELECTION}:
            # PRESTART may still confirm on an ambiguous frame: V3 sometimes misses
            # the start menu while V1 correctly sees 开始赛事 focus. Free roam rarely
            # mis-reads as the start-menu layout, so this fallback is low-risk.
            return screen in {"unknown", "loading_transition", "race_menu", "prestart"}
        if not include_racing:
            return False
        # RACING must be confirmed by a REAL V3 race_hud. smart=RACING on `unknown`
        # is the festival start-line free-roam misread that handed off to the farm
        # prematurely (the car was left idling in free roam). The _decide rule above
        # turns that same misread into "open the pause menu and keep navigating".
        return screen == "race_hud"

    def _buy_phase_needs_driving_disambiguation(self, snapshot: V4Snapshot) -> bool:
        screen = str(getattr(snapshot.v3, "screen", "") or "")
        smart_state = str(getattr(snapshot, "smart_state", "") or "")
        if smart_state != STATE_RACING:
            return False
        if self._buy_phase_can_handoff_to_v4(snapshot):
            return False
        if screen.startswith("pause_") or screen in {"pause_menu", "race_pause_menu", "controller_disconnected"}:
            return False
        return True

    def _join_buy_runner(self, timeout: float = 5.0) -> None:
        thread = getattr(self.buy_runner, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
            if thread.is_alive():
                self.report.errors.append("buy_runner_thread_still_alive_after_stop")
                self._log("V4 warning: BuyCarRunner did not exit within the stop wait window.")

    def _join_smart_runner(self, timeout: float = 5.0) -> None:
        thread = getattr(self.smart_runner, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
            if thread.is_alive():
                self.report.errors.append("smart_runner_thread_still_alive_after_stop")
                self._log("V4 警告：SmartRunner 已请求停止，但线程仍未在等待窗口内结束。")

    def _join_runner(self, runner, timeout: float = 5.0) -> None:
        thread = getattr(runner, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
            if thread.is_alive():
                self.report.errors.append("farm_runner_thread_still_alive_after_stop")
                self._log("V4 警告：刷图器已请求停止，但线程仍未在等待窗口内结束。")

    def _finish(self, completed: bool, reason: str) -> bool:
        self.report.completed = bool(completed)
        self.report.stopped_reason = reason
        self.report.finished_at = datetime.now(timezone.utc).astimezone().isoformat()
        self.write_report()
        if completed:
            self._log("V4 模式三本轮完成。")
        else:
            self._log(f"V4 模式三停止：{reason}")
        return bool(completed)

    def write_report(self) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(self.report)
        path = self.report_dir / "v4_mode3_latest.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _log(self, message: str) -> None:
        self.logger.info(message)
        self.on_log(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run V4 vision-guided V1 mode-3 flow.")
    parser.add_argument("--title", default="Forza")
    parser.add_argument("--model", default=None)
    parser.add_argument("--min-conf", type=float, default=0.42)
    parser.add_argument("--watchdog-seconds", type=float, default=120.0)
    parser.add_argument("--startup-delay", type=float, default=0.0)
    parser.add_argument("--farm-seconds", type=float, default=None)
    parser.add_argument("--skip-buy", action="store_true")
    parser.add_argument("--skip-farm", action="store_true")
    parser.add_argument("--no-exit-after-farm", action="store_true")
    parser.add_argument(
        "--loop-rounds",
        type=int,
        default=1,
        help="Full mode-three outer rounds. 1 = one round, 0 = repeat buy/skill/farm until stopped.",
    )
    parser.add_argument("--auto-focus", action="store_true", help="Use normal foreground activation if Forza is not foreground.")
    parser.add_argument("--allow-background", action="store_true", help="Do not require Forza to be foreground before inputs.")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument(
        "--farm-mode",
        choices=("vision", "smart"),
        default="vision",
        help="Farm loop driver: V3 vision-guided (default) or V1 SmartRunner fallback.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    runner = V4Mode3Runner(
        title=args.title,
        model_path=args.model,
        min_confidence=args.min_conf,
        watchdog_seconds=args.watchdog_seconds,
        report_dir=args.report_dir,
        on_log=print,
    )
    runner._farm_mode = args.farm_mode
    run_kwargs = {
        "startup_delay": args.startup_delay,
        "farm_seconds": args.farm_seconds,
        "run_buy": not args.skip_buy,
        "run_farm": not args.skip_farm,
        "exit_after_farm": not args.no_exit_after_farm,
        "auto_focus": args.auto_focus,
        "require_foreground": not args.allow_background,
    }
    if V4Mode3Runner._loop_rounds(args.loop_rounds) == 1:
        ok = runner.run_once(**run_kwargs)
    else:
        ok = runner.run_loop(**run_kwargs, loop_rounds=args.loop_rounds)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
