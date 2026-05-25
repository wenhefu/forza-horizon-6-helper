"""Screenshot-driven automation loop for Forza EventLab farming."""
import logging
import threading
import time

import config
import focus
from screen_detector import (
    ForzaScreenDetector,
    STATE_CONFIRM_RESTART,
    STATE_CONTROLLER_DISCONNECTED,
    STATE_PAUSE_MENU,
    STATE_PRESTART,
    STATE_PRESTART_WRONG_SELECTION,
    STATE_RACING,
    STATE_RESULTS,
    STATE_UNKNOWN,
)
from window_capture import capture_client


class SmartRunner:
    def __init__(self, on_log=None, logger=None, pad_provider=None):
        self.on_log = on_log or (lambda msg: None)
        self.logger = logger or logging.getLogger("forza6helper")
        self.pad_provider = pad_provider
        self.detector = ForzaScreenDetector()
        self._thread = None
        self._stop = threading.Event()
        self._graceful_exit = threading.Event()
        self.exit_reason = None  # "manual_stop" | "total_time" | "graceful_exit" | "race_exit"

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, startup_delay=0.0, total_seconds=None, auto_focus=True, require_foreground=True):
        if self.is_running():
            self.logger.info("SmartRunner start ignored because it is already running")
            return
        self._stop.clear()
        self.logger.info(
            "SmartRunner starting startup_delay=%.2f total_seconds=%s auto_focus=%s require_foreground=%s",
            startup_delay,
            "unlimited" if total_seconds is None else f"{total_seconds:.2f}",
            auto_focus,
            require_foreground,
        )
        self._thread = threading.Thread(
            target=self._run,
            args=(startup_delay, total_seconds, auto_focus, require_foreground),
            name="smart-runner",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self.logger.info("SmartRunner stop requested")
        self.exit_reason = "manual_stop"
        self._stop.set()

    def request_graceful_exit(self):
        """Ask the runner to exit cleanly at the next results page.

        Instead of pressing X to restart, the runner will press A to leave the
        race and then break the loop so the caller (e.g. ComboRunner) can take
        over the next steps.
        """
        if not self._graceful_exit.is_set():
            self.logger.info("SmartRunner graceful exit requested")
            self.on_log("智能识别：收到平滑退出请求，等当前比赛跑完后按 A 退出。")
        self._graceful_exit.set()

    def detect_once(self):
        hwnd = focus.find_window(config.GAME_TITLE)
        if not hwnd:
            raise RuntimeError(f"没找到标题含“{config.GAME_TITLE}”的游戏窗口。")
        frame = capture_client(hwnd)
        return self.detector.detect(frame)

    def _sleep(self, seconds):
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._stop.is_set():
                return False
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))
        return not self._stop.is_set()

    def _run(self, startup_delay, total_seconds, auto_focus, require_foreground):
        try:
            pad = self.pad_provider()
        except Exception as exc:
            self.logger.exception("Unable to start smart runner gamepad")
            self.on_log(f"无法启动虚拟手柄：{exc}")
            return

        self._graceful_exit.clear()
        self.exit_reason = None

        if startup_delay > 0:
            self.on_log(f"{startup_delay:.0f} 秒后开始智能识别，请保持游戏可见。")
            if not self._sleep(startup_delay):
                pad.neutral()
                self.on_log("已取消。")
                return

        started = time.monotonic()
        lap = 0
        in_race = False
        race_started = None
        last_state = None
        last_focus_log = 0.0
        disconnect_retries = 0
        last_disconnect_retry = 0.0
        disconnect_exhausted_logged = False
        unknown_since = None
        graceful_logged_total = False
        graceful_started_at = None
        overtime_cap = float(
            getattr(config, "COMBO_EVENTLAB_EXIT_MAX_OVERTIME", 15 * 60)
        )
        self.on_log("智能识别已启动：图1先确认光标在开始赛事再按A，图2按住油门，图3按X，图4按A；暂停菜单按B返回。")

        try:
            while not self._stop.is_set():
                if total_seconds is not None and time.monotonic() - started >= total_seconds:
                    if not graceful_logged_total:
                        graceful_logged_total = True
                        graceful_started_at = time.monotonic()
                        self.logger.info("SmartRunner total runtime reached, switching to graceful exit")
                        self.on_log(
                            "总运行时间已到：进入平滑退出，比赛跑完到结算页会按 A 退出，把控制权交给上层。"
                        )
                        self._graceful_exit.set()
                    if (
                        graceful_started_at is not None
                        and time.monotonic() - graceful_started_at >= overtime_cap
                    ):
                        self.logger.info("SmartRunner graceful exit hit overtime cap")
                        self.on_log(
                            f"平滑退出已经等了 {overtime_cap / 60:.0f} 分钟，强制停止；"
                            "如果你需要更长等待，可以改 COMBO_EVENTLAB_EXIT_MAX_OVERTIME。"
                        )
                        self.exit_reason = self.exit_reason or "total_time"
                        break

                if require_foreground and not focus.is_foreground(config.GAME_TITLE):
                    pad.neutral()
                    now = time.monotonic()
                    if now - last_focus_log >= 5.0:
                        self.on_log("游戏不在前台，暂停识别和输入。")
                        last_focus_log = now
                    if auto_focus:
                        focus.activate_window(
                            title_substr=config.GAME_TITLE,
                            on_log=self.on_log,
                            logger=self.logger,
                        )
                    if not self._sleep(1.0):
                        break
                    continue

                try:
                    detection = self.detect_once()
                except Exception as exc:
                    self.logger.exception("Smart screenshot detection failed")
                    self.on_log(f"截图识别失败：{exc}")
                    if not self._sleep(1.0):
                        break
                    continue

                state = detection.state
                if state != last_state:
                    self.logger.info(
                        "Smart state=%s confidence=%.3f scores=%s",
                        state,
                        detection.confidence,
                        {k: round(v, 4) for k, v in detection.scores.items()},
                    )
                    self.on_log(f"识别到：{self._state_label(state)}")
                    last_state = state
                    if state != STATE_UNKNOWN:
                        unknown_since = None
                    if state != STATE_CONTROLLER_DISCONNECTED:
                        disconnect_retries = 0
                        last_disconnect_retry = 0.0
                        disconnect_exhausted_logged = False

                if state == STATE_PRESTART:
                    in_race = False
                    pad.neutral()
                    self.on_log("图1：按 A 开始赛事。")
                    pad.tap("a", hold=0.15)
                    if not self._sleep(config.SMART_MENU_POLL_SECONDS * 2):
                        break

                elif state == STATE_PRESTART_WRONG_SELECTION:
                    in_race = False
                    pad.neutral()
                    self.on_log("图1光标不在“开始竞赛赛事”，按十字键上校准后再识别。")
                    pad.tap("dpad_up", hold=0.12)
                    if not self._sleep(config.SMART_MENU_POLL_SECONDS):
                        break

                elif state == STATE_PAUSE_MENU:
                    pad.neutral()
                    in_race = False
                    self.on_log("检测到暂停菜单，按 B 返回比赛/赛事页面后重新识别。")
                    pad.tap("b", hold=0.15)
                    if not self._sleep(config.SMART_MENU_POLL_SECONDS * 2):
                        break

                elif state == STATE_RACING:
                    if not in_race:
                        race_started = time.monotonic()
                        in_race = True
                        self.on_log("图2：进入比赛，保持油门。")
                    pad.apply(throttle=1.0)
                    if not self._sleep(self._race_poll_interval(race_started)):
                        break

                elif state == STATE_RESULTS:
                    pad.neutral()
                    in_race = False
                    lap += 1
                    if self._graceful_exit.is_set():
                        self.on_log(
                            f"图3：第 {lap} 圈完成，平滑退出：按 A 退出比赛，让组合模式接管。"
                        )
                        pad.tap("a", hold=0.15)
                        self.exit_reason = self.exit_reason or "graceful_exit"
                        if not self._sleep(config.SMART_MENU_POLL_SECONDS * 3):
                            break
                        self.logger.info("SmartRunner exiting after graceful A on results")
                        break
                    self.on_log(f"图3：第 {lap} 圈完成，按 X 重来。")
                    pad.tap("x", hold=0.15)
                    if not self._sleep(config.SMART_MENU_POLL_SECONDS):
                        break

                elif state == STATE_CONFIRM_RESTART:
                    pad.neutral()
                    in_race = False
                    if self._graceful_exit.is_set():
                        # We were in the middle of pressing X→A loop. The user wants
                        # us to back out, so press B to dismiss the confirm modal and
                        # wait for results again (where we'll press A instead).
                        self.on_log(
                            "图4：平滑退出中，按 B 取消重开，等下次结算页用 A 退出。"
                        )
                        pad.tap("b", hold=0.15)
                        if not self._sleep(config.SMART_MENU_POLL_SECONDS * 2):
                            break
                        continue
                    self.on_log("图4：按 A 确认重开。")
                    pad.tap("a", hold=0.15)
                    if not self._sleep(config.SMART_MENU_POLL_SECONDS * 2):
                        break

                elif state == STATE_CONTROLLER_DISCONNECTED:
                    pad.neutral()
                    in_race = False
                    now = time.monotonic()
                    if disconnect_retries == 0:
                        self.on_log("检测到控制器未连接弹窗：尝试按 A 恢复。")
                    if (
                        disconnect_retries < config.SMART_DISCONNECT_MAX_RETRIES
                        and now - last_disconnect_retry >= config.SMART_DISCONNECT_RETRY_SECONDS
                    ):
                        disconnect_retries += 1
                        last_disconnect_retry = now
                        self.on_log(
                            f"控制器弹窗恢复尝试 {disconnect_retries}/"
                            f"{config.SMART_DISCONNECT_MAX_RETRIES}：按 A。"
                        )
                        pad.tap("a", hold=0.15)
                    elif (
                        disconnect_retries >= config.SMART_DISCONNECT_MAX_RETRIES
                        and not disconnect_exhausted_logged
                    ):
                        self.on_log("控制器弹窗仍存在：保持等待，不再连续按键。")
                        disconnect_exhausted_logged = True
                    if not self._sleep(config.SMART_UNKNOWN_POLL_SECONDS):
                        break

                else:
                    if in_race:
                        pad.apply(throttle=1.0)
                        if not self._sleep(config.SMART_RACE_POLL_SECONDS):
                            break
                    else:
                        pad.neutral()
                        if unknown_since is None:
                            unknown_since = time.monotonic()
                        unknown_age = time.monotonic() - unknown_since
                        if unknown_age > 8.0 and state == STATE_UNKNOWN:
                            self.on_log("仍是未知画面：等待稳定，暂不按键。")
                            unknown_since = time.monotonic()
                        if not self._sleep(config.SMART_UNKNOWN_POLL_SECONDS):
                            break
        except Exception as exc:
            self.logger.exception("SmartRunner crashed")
            self.on_log(f"智能识别运行时出错：{exc}")
        finally:
            pad.neutral()
            self.on_log("智能识别已停止，手柄保持连接并已回正。")

    @staticmethod
    def _race_poll_interval(race_started):
        if race_started is None:
            return config.SMART_RACE_EARLY_POLL_SECONDS
        elapsed = time.monotonic() - race_started
        if elapsed < config.SMART_RACE_EARLY_SECONDS:
            return config.SMART_RACE_EARLY_POLL_SECONDS
        return config.SMART_RACE_POLL_SECONDS

    @staticmethod
    def _state_label(state):
        labels = {
            STATE_PRESTART: "图1 开始赛事菜单",
            STATE_PRESTART_WRONG_SELECTION: "图1 菜单光标不在开始赛事",
            STATE_PAUSE_MENU: "暂停菜单/剧情页",
            STATE_RACING: "图2 正在游玩",
            STATE_RESULTS: "图3 完赛结果页",
            STATE_CONFIRM_RESTART: "图4 重开确认页",
            STATE_CONTROLLER_DISCONNECTED: "控制器未连接弹窗",
            STATE_UNKNOWN: "未知画面",
        }
        return labels.get(state, state)
