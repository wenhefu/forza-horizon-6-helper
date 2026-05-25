"""Screenshot-driven Subaru 22B purchase flow."""
import logging
import threading
import time

import config
import focus
from ocr_engine import OcrReader
from buy_car_detector import (
    BuyCarScreenDetector,
    STATE_AUTOSHOW_GRID,
    STATE_BUY_SELL_MENU,
    STATE_BUY_SELL_SHOWROOM_READY,
    STATE_CAR_PREVIEW,
    STATE_COLOR_SELECT,
    STATE_CONFIRM_MODAL,
    STATE_CONTROLLER_DISCONNECTED,
    STATE_DESIGN_GRID,
    STATE_EVENTLAB_FILTER,
    STATE_EVENTLAB_FAVORITES,
    STATE_EVENTLAB_MY_CARS,
    STATE_EVENTLAB_MY_CARS_22B_READY,
    STATE_EVENTLAB_RACE_TYPE,
    STATE_MANUFACTURER_GRID,
    STATE_MANUFACTURER_SUBARU_READY,
    STATE_PAUSE_CARS,
    STATE_PAUSE_MENU,
    STATE_POST_PURCHASE_VIEW,
    STATE_PURCHASE_CONFIRM,
    STATE_SEARCH_DIALOG,
    STATE_SKILL_MASTERY,
    STATE_SKILL_POINTS_EXHAUSTED,
    STATE_SUBARU_22B_READY,
    STATE_SUBARU_GRID,
    STATE_UPGRADE_MENU,
    STATE_VEHICLE_TAB,
    STATE_UNKNOWN,
)
from window_capture import capture_client, capture_client_printwindow


class BuyCarRunner:
    def __init__(self, on_log=None, logger=None, pad_provider=None):
        self.on_log = on_log or (lambda msg: None)
        self.logger = logger or logging.getLogger("forza6helper")
        self.pad_provider = pad_provider
        self.detector = BuyCarScreenDetector()
        self.ocr = OcrReader(logger=self.logger)
        self._last_ocr_at = 0.0
        self._last_ocr_items = []
        self._thread = None
        self._stop = threading.Event()
        self.stop_reason = None
        self.points_exhausted = False

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, startup_delay=0.0, total_seconds=None, auto_focus=True, require_foreground=True):
        if self.is_running():
            self.logger.info("BuyCarRunner start ignored because it is already running")
            return
        self._stop.clear()
        self.stop_reason = None
        self.points_exhausted = False
        self.logger.info(
            "BuyCarRunner starting startup_delay=%.2f total_seconds=%s auto_focus=%s require_foreground=%s",
            startup_delay,
            "unlimited" if total_seconds is None else f"{total_seconds:.2f}",
            auto_focus,
            require_foreground,
        )
        self._thread = threading.Thread(
            target=self._run,
            args=(startup_delay, total_seconds, auto_focus, require_foreground),
            name="buy-car-runner",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self.logger.info("BuyCarRunner stop requested")
        self._stop.set()

    def detect_once(self):
        hwnd = focus.find_window(config.GAME_TITLE)
        if not hwnd:
            raise RuntimeError(f"没找到标题含“{config.GAME_TITLE}”的游戏窗口。")
        frame = capture_client(hwnd)
        detection = self.detector.detect(frame)
        if config.BUY_OCR_ENABLED and self._should_ocr(detection):
            try:
                ocr_frame = capture_client_printwindow(hwnd)
            except Exception:
                ocr_frame = frame
            ocr_detection = self.detector.detect(ocr_frame)
            if ocr_detection.state != STATE_UNKNOWN and (
                detection.state == STATE_UNKNOWN or ocr_detection.confidence >= detection.confidence
            ):
                detection = ocr_detection
            items = self._read_ocr(hwnd, frame=ocr_frame, force=detection.state == STATE_UNKNOWN)
            detection = self.detector.refine_with_ocr(
                detection,
                items,
                frame=ocr_frame if items else frame,
            )
        return detection

    def _should_ocr(self, detection):
        return detection.state in {
            STATE_UNKNOWN,
            STATE_CONFIRM_MODAL,
            STATE_CONTROLLER_DISCONNECTED,
            STATE_PURCHASE_CONFIRM,
            STATE_SEARCH_DIALOG,
            STATE_PAUSE_MENU,
            STATE_PAUSE_CARS,
            STATE_BUY_SELL_MENU,
            STATE_BUY_SELL_SHOWROOM_READY,
            STATE_AUTOSHOW_GRID,
            STATE_MANUFACTURER_GRID,
            STATE_MANUFACTURER_SUBARU_READY,
            STATE_SUBARU_GRID,
            STATE_SUBARU_22B_READY,
            STATE_DESIGN_GRID,
            STATE_COLOR_SELECT,
            STATE_CAR_PREVIEW,
            STATE_POST_PURCHASE_VIEW,
            STATE_VEHICLE_TAB,
            STATE_UPGRADE_MENU,
            STATE_SKILL_MASTERY,
            STATE_SKILL_POINTS_EXHAUSTED,
        }

    def _read_ocr(self, hwnd, frame=None, force=False):
        now = time.monotonic()
        if (
            not force
            and self._last_ocr_items
            and now - self._last_ocr_at < config.BUY_OCR_MIN_INTERVAL_SECONDS
        ):
            return self._last_ocr_items
        if frame is None:
            items = self.ocr.read_window(hwnd, min_confidence=config.BUY_OCR_MIN_CONFIDENCE)
        else:
            items = self.ocr.read_frame(frame, min_confidence=config.BUY_OCR_MIN_CONFIDENCE)
        self._last_ocr_at = now
        self._last_ocr_items = items
        if items:
            preview = " | ".join(item.text for item in items[:12])
            self.logger.info("BuyCar OCR text: %s", preview)
            if getattr(config, "BUY_OCR_LOG_ITEMS", False):
                details = []
                for item in items[:90]:
                    details.append(
                        f"{item.text}@({getattr(item, 'ncx', 0.0):.3f},{getattr(item, 'ncy', 0.0):.3f})"
                    )
                self.logger.info("BuyCar OCR items: %s", " | ".join(details))
        elif not self.ocr.available:
            self.logger.info("BuyCar OCR unavailable: %s", self.ocr.last_error)
        return items

    def _invalidate_ocr(self):
        self._last_ocr_at = 0.0
        self._last_ocr_items = []

    def _sleep(self, seconds):
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._stop.is_set():
                return False
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))
        return not self._stop.is_set()

    def _tap(self, pad, button, hold=0.15, after=None):
        self._invalidate_ocr()
        pad.tap(button, hold=hold)
        self._invalidate_ocr()
        return self._sleep(config.BUY_ACTION_DELAY_SECONDS if after is None else after)

    def _tap_many(self, pad, button, count, after_each=0.12):
        for _ in range(count):
            if self._stop.is_set():
                return False
            self._invalidate_ocr()
            pad.tap(button, hold=0.08)
            self._invalidate_ocr()
            if not self._sleep(after_each):
                return False
        return True

    def _run(self, startup_delay, total_seconds, auto_focus, require_foreground):
        try:
            pad = self.pad_provider()
        except Exception as exc:
            self.logger.exception("Unable to start buy-car runner gamepad")
            self.on_log(f"无法启动虚拟手柄：{exc}")
            return

        if startup_delay > 0:
            self.on_log(f"{startup_delay:.0f} 秒后开始买车流程，请保持游戏可见。")
            if not self._sleep(startup_delay):
                pad.neutral()
                self.on_log("已取消。")
                return

        started = time.monotonic()
        last_state = None
        last_focus_log = 0.0
        opened_pause = False
        made_progress = False
        manufacturer_nav_stage = 0
        manufacturer_confirm_waits = 0
        manufacturer_last_move = None
        manufacturer_search_attempts = 0
        subaru_nav_done = False
        subaru_nav_steps = 0
        subaru_last_move = None
        pause_purchase_nav_steps = 0
        showroom_nav_done = False
        vehicle_upgrade_nav_done = False
        upgrade_mastery_nav_done = False
        mastery_ready_for_sequence = False
        purchase_confirmed = False
        purchase_path_armed = False
        need_upgrade = False
        return_to_buy_tab = False
        mastery_sequence_done = False
        cars_bought = 0
        unknown_since = None
        self.on_log("买车加点模式已启动：购买斯巴鲁 22B，买熟练度抽奖精灵，再回车展循环。")

        try:
            while not self._stop.is_set():
                if total_seconds is not None and time.monotonic() - started >= total_seconds:
                    self.logger.info("BuyCarRunner total runtime reached")
                    self.on_log("总运行时间已到，买车流程停止并回正手柄。")
                    break

                if require_foreground and not focus.is_foreground(config.GAME_TITLE):
                    pad.neutral()
                    now = time.monotonic()
                    if now - last_focus_log >= 5.0:
                        self.on_log("游戏不在前台，暂停买车流程和输入。")
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
                    self.logger.exception("Buy-car screenshot detection failed")
                    self.on_log(f"截图识别失败：{exc}")
                    if not self._sleep(1.0):
                        break
                    continue

                state = detection.state
                if (
                    state == STATE_PAUSE_CARS
                    and need_upgrade
                    and detection.scores.get("ocr_vehicle_upgrade_seen", 0.0) >= 0.5
                    and detection.scores.get("ocr_pause_purchase_seen", 0.0) < 0.5
                ):
                    self.on_log("车辆页：买车后已看到“升级与调校”，按加点车辆页处理。")
                    state = STATE_VEHICLE_TAB
                elif (
                    state == STATE_VEHICLE_TAB
                    and not need_upgrade
                    and not return_to_buy_tab
                    and detection.scores.get("ocr_pause_purchase_seen", 0.0) >= 0.5
                ):
                    self.on_log("车辆页：看到“购买新车/二手车”，按买车入口页处理。")
                    state = STATE_PAUSE_CARS
                if state != last_state:
                    self.logger.info(
                        "BuyCar state=%s confidence=%.3f scores=%s",
                        state,
                        detection.confidence,
                        {k: round(v, 4) for k, v in detection.scores.items()},
                    )
                    self.on_log(f"买车识别到：{self._state_label(state)}")
                    if detection.ocr_text:
                        self.on_log(f"OCR：{detection.ocr_text[:140]}")
                    last_state = state
                    if state != STATE_UNKNOWN:
                        unknown_since = None
                        made_progress = True

                if purchase_confirmed and state not in (STATE_PURCHASE_CONFIRM, STATE_CONTROLLER_DISCONNECTED):
                    if state == STATE_UNKNOWN:
                        if unknown_since is None:
                            unknown_since = time.monotonic()
                        if time.monotonic() - unknown_since < 2.0:
                            if not self._sleep(config.BUY_POLL_SECONDS):
                                break
                            continue
                    cars_bought += 1
                    purchase_confirmed = False
                    purchase_path_armed = False
                    vehicle_upgrade_nav_done = False
                    upgrade_mastery_nav_done = False
                    need_upgrade = True
                    self.on_log(
                        f"购买后页面：第 {cars_bought} 辆 22B 已购买，按 B 返回，然后去车辆熟练度加点。"
                    )
                    if not self._tap(pad, "b", after=1.2):
                        break
                    unknown_since = None
                    continue

                if state == STATE_PURCHASE_CONFIRM:
                    pad.neutral()
                    if not purchase_path_armed:
                        self.on_log("购买确认弹窗：尚未确认选中 22B，按 B 取消，避免误买。")
                        purchase_confirmed = False
                        if not self._tap(pad, "b", after=1.0):
                            break
                        continue
                    if not purchase_confirmed:
                        self.on_log("购买确认弹窗：按 A 购买，然后等待新车展示页。")
                        purchase_confirmed = True
                        if not self._tap(pad, "a", after=2.0):
                            break
                    else:
                        self.on_log("已提交购买，等待页面切换。")
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                    continue

                if state == STATE_CONTROLLER_DISCONNECTED:
                    pad.neutral()
                    self.on_log("控制器未连接弹窗：按 A 恢复手柄，然后重新识别当前页面。")
                    opened_pause = False
                    unknown_since = None
                    if not self._tap(pad, "a", after=1.0):
                        break
                    continue

                if state == STATE_SEARCH_DIALOG:
                    pad.neutral()
                    self.on_log("搜索/筛选弹窗：按 B 取消，回到上一级页面。")
                    if not self._tap(pad, "b", after=1.0):
                        break
                    continue

                if state == STATE_SKILL_POINTS_EXHAUSTED:
                    pad.neutral()
                    self.points_exhausted = True
                    self.stop_reason = "points_exhausted"
                    self.on_log("车辆熟练度：技术点数不足，买车阶段暂停在不足弹窗。")
                    break

                if state == STATE_CONFIRM_MODAL:
                    pad.neutral()
                    self.on_log("确认弹窗：按 A 选择“嗯”。")
                    if not self._tap(pad, "a"):
                        break
                    continue

                if state == STATE_PAUSE_MENU:
                    pad.neutral()
                    if pause_purchase_nav_steps:
                        self.on_log("车辆入口导航后回到其他暂停页，说明刚才越过入口；先重置，下一次再切回车辆页。")
                        pause_purchase_nav_steps = 0
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue
                    self.on_log("暂停菜单：按 RB 切到“车辆”。")
                    pause_purchase_nav_steps = 0
                    if not self._tap(pad, "rb", after=1.2):
                        break
                    continue

                if state == STATE_PAUSE_CARS:
                    pad.neutral()
                    if detection.scores.get("ocr_used", 0.0) and detection.scores.get("ocr_pause_purchase_seen", 0.0) < 0.5:
                        self.on_log("车辆页：OCR 未看到“购买新车与二手车”，先不按 A，等待重新识别。")
                        pause_purchase_nav_steps = 0
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue
                    if detection.scores.get("pause_purchase_focus_lime", 0.0) >= 0.12:
                        self.on_log("车辆页：确认光标在“购买新车与二手车”，按 A。")
                        pause_purchase_nav_steps = 0
                        if not self._tap(pad, "a", after=1.2):
                            break
                        continue
                    if pause_purchase_nav_steps >= 3:
                        self.on_log("车辆页：连续左移后仍未确认入口高亮，暂停按键，等待重新识别。")
                        pause_purchase_nav_steps = 0
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue
                    pause_purchase_nav_steps += 1
                    self.on_log(f"车辆页：入口可见但未高亮，左移 1 格后重新识别（第 {pause_purchase_nav_steps} 次）。")
                    if not self._tap(pad, "dpad_left", after=0.7):
                        break
                    continue

                if state == STATE_BUY_SELL_MENU:
                    pad.neutral()
                    pause_purchase_nav_steps = 0
                    if need_upgrade:
                        self.on_log("购买与出售页：新车已买，按 RB 切到车辆页。")
                        vehicle_upgrade_nav_done = False
                        if not self._tap(pad, "rb", after=1.2):
                            break
                        continue
                    if return_to_buy_tab:
                        return_to_buy_tab = False
                        mastery_sequence_done = False
                        manufacturer_nav_stage = 0
                        manufacturer_confirm_waits = 0
                        manufacturer_last_move = None
                        manufacturer_search_attempts = 0
                        subaru_nav_done = False
                        subaru_nav_steps = 0
                        subaru_last_move = None
                        purchase_confirmed = False
                        purchase_path_armed = False
                        need_upgrade = False
                        showroom_nav_done = False
                        self.on_log("已回到购买与出售页，准备循环购买下一辆 22B。")
                    if not showroom_nav_done:
                        self.on_log("购买与出售页：先把光标校准到“车展”，下一次识别确认后再进入。")
                        if not self._tap_many(pad, "dpad_up", 5):
                            break
                        showroom_nav_done = True
                    else:
                        self.on_log("购买与出售页：等待“车展”高亮确认，暂不按 A。")
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                    continue

                if state == STATE_BUY_SELL_SHOWROOM_READY:
                    pad.neutral()
                    pause_purchase_nav_steps = 0
                    if need_upgrade:
                        self.on_log("购买与出售页：新车已买，按 RB 切到车辆页。")
                        vehicle_upgrade_nav_done = False
                        if not self._tap(pad, "rb", after=1.2):
                            break
                        continue
                    if return_to_buy_tab:
                        return_to_buy_tab = False
                        mastery_sequence_done = False
                        manufacturer_nav_stage = 0
                        manufacturer_confirm_waits = 0
                        manufacturer_last_move = None
                        manufacturer_search_attempts = 0
                        subaru_nav_done = False
                        subaru_nav_steps = 0
                        subaru_last_move = None
                        purchase_confirmed = False
                        purchase_path_armed = False
                        need_upgrade = False
                        showroom_nav_done = False
                        self.on_log("已回到购买与出售页，准备循环购买下一辆 22B。")
                    self.on_log("购买与出售页：光标在“车展”，按 A。")
                    showroom_nav_done = False
                    if not self._tap(pad, "a", after=1.2):
                        break
                    continue

                if state == STATE_AUTOSHOW_GRID:
                    pad.neutral()
                    if detection.scores.get("ocr_used", 0.0) and detection.scores.get("ocr_autoshow_grid_seen", 0.0) < 0.5:
                        self.on_log("购买车辆页：OCR 未确认是车展网格，先不按 View/Back。")
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue
                    manufacturer_nav_stage = 0
                    manufacturer_confirm_waits = 0
                    manufacturer_last_move = None
                    manufacturer_search_attempts = 0
                    subaru_nav_done = False
                    subaru_nav_steps = 0
                    subaru_last_move = None
                    purchase_path_armed = False
                    self.on_log("购买车辆页：按 View/Back 前往制造商列表。")
                    if not self._tap(pad, "back", after=1.0):
                        break
                    continue

                if state == STATE_MANUFACTURER_GRID:
                    pad.neutral()
                    showroom_nav_done = False
                    target_col = int(detection.scores.get("ocr_manufacturer_target_col", 0.0))
                    target_row = int(detection.scores.get("ocr_manufacturer_target_row", 0.0))
                    selected_col = int(detection.scores.get("ocr_manufacturer_selected_col", 0.0))
                    selected_row = int(detection.scores.get("ocr_manufacturer_selected_row", 0.0))
                    target_visible = target_col > 0 and target_row > 0

                    if not target_visible:
                        if manufacturer_last_move:
                            rollback = self._opposite_move(manufacturer_last_move)
                            self.on_log(f"制造商列表：上一步后看不到斯巴鲁，回退 {self._move_label(rollback)}。")
                            manufacturer_last_move = None
                            if not self._tap(pad, rollback, after=0.8):
                                break
                            continue
                        if manufacturer_search_attempts >= 10:
                            self.on_log("制造商列表：连续搜索仍未看到斯巴鲁，暂停按键等待人工检查。")
                            if not self._sleep(config.BUY_POLL_SECONDS):
                                break
                            continue
                        manufacturer_search_attempts += 1
                        manufacturer_last_move = "dpad_up"
                        self.on_log(f"制造商列表：当前页未见斯巴鲁，按上搜索一页/一行（第 {manufacturer_search_attempts} 次）。")
                        if not self._tap(pad, "dpad_up", after=0.8):
                            break
                        continue

                    manufacturer_search_attempts = 0
                    if not selected_col or not selected_row:
                        self.on_log("制造商列表：看得到斯巴鲁，但未识别当前光标位置，等待下一次截图，不按键。")
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue

                    row_delta = target_row - selected_row
                    col_delta = target_col - selected_col
                    if row_delta == 0 and col_delta == 0:
                        self.on_log("制造商列表：斯巴鲁已在当前光标，等待高亮确认。")
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue

                    if row_delta:
                        move = "dpad_down" if row_delta > 0 else "dpad_up"
                    else:
                        move = "dpad_right" if col_delta > 0 else "dpad_left"
                    manufacturer_last_move = move
                    self.on_log(
                        f"制造商列表：目标({target_col},{target_row})，当前({selected_col},{selected_row})，"
                        f"移动 {self._move_label(move)} 1 格。"
                    )
                    if not self._tap(pad, move, after=0.8):
                        break
                    continue

                if state == STATE_MANUFACTURER_SUBARU_READY:
                    pad.neutral()
                    if detection.scores.get("ocr_used", 0.0) and (
                        detection.scores.get("ocr_manufacturer_target_col", 0.0) < 0.5
                        or detection.scores.get("ocr_manufacturer_selected_col", 0.0)
                        != detection.scores.get("ocr_manufacturer_target_col", 0.0)
                        or detection.scores.get("ocr_manufacturer_selected_row", 0.0)
                        != detection.scores.get("ocr_manufacturer_target_row", 0.0)
                    ):
                        self.on_log("制造商列表：状态疑似已选中，但 OCR 坐标不一致，先不按 A。")
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue
                    self.on_log("制造商列表：已在斯巴鲁，按 A 进入。")
                    if not self._tap(pad, "a", after=1.2):
                        break
                    manufacturer_nav_stage = 0
                    manufacturer_confirm_waits = 0
                    manufacturer_last_move = None
                    manufacturer_search_attempts = 0
                    subaru_nav_done = False
                    subaru_nav_steps = 0
                    subaru_last_move = None
                    purchase_path_armed = False
                    continue

                if state == STATE_SUBARU_GRID:
                    pad.neutral()
                    manufacturer_nav_stage = 0
                    manufacturer_confirm_waits = 0
                    target_col = int(detection.scores.get("ocr_subaru_22b_target_col", 0.0))
                    selected_index = int(detection.scores.get("ocr_subaru_selected_col", 0.0))
                    target_visible = target_col > 0

                    if selected_index and target_visible and selected_index == target_col:
                        self.on_log("斯巴鲁车展：目标卡已高亮，等待 22B 文本与高亮双确认。")
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue

                    if not target_visible:
                        if subaru_last_move:
                            rollback = self._opposite_move(subaru_last_move)
                            self.on_log(f"斯巴鲁车展：上一步后 22B 离开页面，回退 {self._move_label(rollback)}。")
                            subaru_last_move = None
                            if not self._tap(pad, rollback, after=0.8):
                                break
                            continue
                        self.on_log("斯巴鲁车展：当前页看不到 22B，按 View/Back 回制造商列表重置路径。")
                        subaru_nav_steps = 0
                        manufacturer_nav_stage = 0
                        if not self._tap(pad, "back", after=1.0):
                            break
                        continue

                    if not selected_index:
                        self.on_log("斯巴鲁车展：看得到 22B 但未确认当前高亮，等待重新识别，不按方向键。")
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue

                    delta = target_col - selected_index
                    if delta == 0:
                        self.on_log("斯巴鲁车展：目标列与高亮列一致但确认不足，等待下一次 OCR。")
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue

                    if abs(delta) > 1 and subaru_nav_steps >= 8:
                        self.on_log("斯巴鲁车展：多次移动后仍未对齐 22B，回制造商列表重置，避免继续把 22B 推出屏幕。")
                        subaru_nav_steps = 0
                        subaru_last_move = None
                        manufacturer_nav_stage = 0
                        if not self._tap(pad, "back", after=1.0):
                            break
                        continue

                    button = "dpad_right" if delta > 0 else "dpad_left"
                    subaru_nav_steps += 1
                    subaru_last_move = button
                    self.on_log(f"斯巴鲁车展：22B 在第 {target_col} 张，当前第 {selected_index} 张，移动 {self._move_label(button)} 1 格。")
                    if not self._tap(pad, button, after=0.75):
                        break
                    continue

                if state == STATE_SUBARU_22B_READY:
                    pad.neutral()
                    if detection.scores.get("ocr_used", 0.0) and detection.scores.get("ocr_subaru_22b_selected_seen", 0.0) < 0.5:
                        self.on_log("斯巴鲁车展：状态疑似 22B 已选中，但 OCR/高亮未双确认，先不购买。")
                        if not self._sleep(config.BUY_POLL_SECONDS):
                            break
                        continue
                    self.on_log("斯巴鲁车展：22B 已选中，按 A。")
                    if not self._tap(pad, "a", after=1.2):
                        break
                    subaru_nav_steps = 0
                    subaru_last_move = None
                    purchase_path_armed = True
                    continue

                if state == STATE_DESIGN_GRID:
                    pad.neutral()
                    if not purchase_path_armed:
                        self.on_log("推荐设计页：尚未确认是 22B 路径，按 B 返回，避免继续误买。")
                        if not self._tap(pad, "b", after=1.0):
                            break
                        continue
                    self.on_log("推荐设计页：按 Y 进入颜色/出厂颜色。")
                    if not self._tap(pad, "y", after=1.0):
                        break
                    continue

                if state == STATE_COLOR_SELECT:
                    pad.neutral()
                    if not purchase_path_armed:
                        self.on_log("出厂颜色页：尚未确认是 22B 路径，按 B 返回，避免继续误买。")
                        if not self._tap(pad, "b", after=1.0):
                            break
                        continue
                    self.on_log("出厂颜色页：按 A 确认默认颜色。")
                    if not self._tap(pad, "a", after=1.0):
                        break
                    continue

                if state == STATE_CAR_PREVIEW:
                    pad.neutral()
                    if not purchase_path_armed:
                        self.on_log("车辆预览页：尚未确认选中 22B，按 B 返回，绝不购买当前车辆。")
                        if not self._tap(pad, "b", after=1.0):
                            break
                        continue
                    self.on_log("车辆预览页：按 A 进入购买确认。")
                    if not self._tap(pad, "a", after=1.0):
                        break
                    continue

                if state == STATE_POST_PURCHASE_VIEW:
                    pad.neutral()
                    if purchase_confirmed:
                        cars_bought += 1
                    purchase_confirmed = False
                    purchase_path_armed = False
                    vehicle_upgrade_nav_done = False
                    upgrade_mastery_nav_done = False
                    if cars_bought:
                        self.on_log(f"新车展示页：第 {cars_bought} 辆 22B 已购买，按 B 返回购买与出售页。")
                    else:
                        self.on_log("新车展示页：按 B 返回购买与出售页。")
                    need_upgrade = True
                    if not self._tap(pad, "b", after=1.0):
                        break
                    continue

                if state == STATE_VEHICLE_TAB:
                    pad.neutral()
                    if return_to_buy_tab:
                        self.on_log("车辆页：熟练度已买完，按 LB 回到购买与出售页。")
                        showroom_nav_done = False
                        if not self._tap(pad, "lb", after=1.2):
                            break
                    else:
                        need_upgrade = False
                        if detection.scores.get("ocr_used", 0.0) and detection.scores.get("ocr_vehicle_upgrade_seen", 0.0) < 0.5:
                            self.on_log("车辆页：OCR 未看到“升级与调校”，先不按 A。")
                            vehicle_upgrade_nav_done = False
                            if not self._sleep(config.BUY_POLL_SECONDS):
                                break
                            continue
                        if not vehicle_upgrade_nav_done:
                            self.on_log("车辆页：移动到“升级与调校”，下一次识别确认后再进入。")
                            if not self._tap_many(pad, "dpad_up", 8):
                                break
                            if not self._tap(pad, "dpad_down", after=0.55):
                                break
                            vehicle_upgrade_nav_done = True
                            continue
                        self.on_log("车辆页：已校准到“升级与调校”，按 A。")
                        vehicle_upgrade_nav_done = False
                        if not self._tap(pad, "a", after=1.2):
                            break
                    continue

                if state == STATE_UPGRADE_MENU:
                    pad.neutral()
                    if return_to_buy_tab:
                        self.on_log("升级页：按 B 返回车辆页。")
                        vehicle_upgrade_nav_done = False
                        if not self._tap(pad, "b", after=1.0):
                            break
                    else:
                        if detection.scores.get("ocr_used", 0.0) and detection.scores.get("ocr_upgrade_mastery_seen", 0.0) < 0.5:
                            self.on_log("升级页：OCR 未看到“车辆熟练度”，先不按 A。")
                            upgrade_mastery_nav_done = False
                            if not self._sleep(config.BUY_POLL_SECONDS):
                                break
                            continue
                        if not upgrade_mastery_nav_done:
                            self.on_log("升级页：移动到“车辆熟练度”，下一次识别确认后再进入。")
                            if not self._tap_many(pad, "dpad_up", 8):
                                break
                            if not self._tap_many(pad, "dpad_down", 7):
                                break
                            upgrade_mastery_nav_done = True
                            continue
                        self.on_log("升级页：已校准到“车辆熟练度”，按 A。")
                        upgrade_mastery_nav_done = False
                        mastery_ready_for_sequence = True
                        if not self._tap(pad, "a", after=1.2):
                            break
                    continue

                if state == STATE_SKILL_MASTERY:
                    pad.neutral()
                    if not mastery_sequence_done:
                        if not mastery_ready_for_sequence:
                            self.on_log("车辆熟练度：不是刚从升级页进入的默认光标，先按 B 返回重进，避免从半路乱按。")
                            upgrade_mastery_nav_done = False
                            if not self._tap(pad, "b", after=1.0):
                                break
                            continue
                        self.on_log("车辆熟练度：购买路径到“抽奖精灵”。")
                        if not self._buy_wheelspin_path(pad):
                            break
                        mastery_sequence_done = True
                        mastery_ready_for_sequence = False
                        return_to_buy_tab = True
                        self.on_log("抽奖精灵路径已购买，按 B 返回升级页。")
                        if not self._tap(pad, "b", after=1.0):
                            break
                    else:
                        self.on_log("车辆熟练度已处理，按 B 返回。")
                        if not self._tap(pad, "b", after=1.0):
                            break
                    continue

                if state == STATE_UNKNOWN:
                    pad.neutral()
                    if unknown_since is None:
                        unknown_since = time.monotonic()
                    age = time.monotonic() - unknown_since
                    scores = detection.scores
                    if (
                        age >= 1.0
                        and scores.get("modal_lime", 0.0) >= 0.20
                        and scores.get("modal_white_option", 0.0) < 0.03
                        and scores.get("modal_price_yellow", 0.0) < 0.02
                    ):
                        self.on_log("疑似控制器未连接弹窗：先按 A 恢复，再重新识别。")
                        opened_pause = False
                        if not self._tap(pad, "a", after=1.0):
                            break
                        unknown_since = time.monotonic()
                        continue
                    if age >= 1.0 and scores.get("pause_teal", 0.0) >= 0.12:
                        self.on_log("疑似已经在暂停菜单：先按 RB 切到车辆页，避免按 Start 退出暂停。")
                        opened_pause = True
                        pause_purchase_nav_steps = 0
                        if not self._tap(pad, "rb", after=1.2):
                            break
                        unknown_since = time.monotonic()
                        continue
                    if not opened_pause and not made_progress and age >= 1.0:
                        self.on_log("未知画面：按 Menu/Start 尝试打开暂停菜单。")
                        opened_pause = True
                        if not self._tap(pad, "start", after=1.0):
                            break
                    elif age >= 8.0:
                        self.on_log("仍是未知画面：等待稳定，暂不连续乱按。")
                        unknown_since = time.monotonic()
                    if not self._sleep(config.BUY_POLL_SECONDS):
                        break
        except Exception as exc:
            self.logger.exception("BuyCarRunner crashed")
            self.on_log(f"买车流程运行时出错：{exc}")
            self.stop_reason = self.stop_reason or "error"
        finally:
            if self._stop.is_set():
                self.stop_reason = self.stop_reason or "stopped"
            pad.neutral()
            self.on_log("买车加点模式已停止，手柄保持连接并已回正。")

    def _buy_wheelspin_path(self, pad):
        # Only run this immediately after entering the 22B mastery page from the
        # upgrade menu, where the cursor is always on the lower-left first node.
        steps = [
            ("a", "第一个点", 1.10),
            ("dpad_right", "右移一次", 0.55),
            ("a", "第二个点", 1.10),
            ("dpad_up", "上移一次", 0.55),
            ("a", "第三个点", 1.10),
            ("dpad_up", "上移一次", 0.55),
            ("a", "第四个点", 1.10),
            ("dpad_up", "上移一次", 0.55),
            ("a", "第五个点", 1.20),
            ("dpad_left", "左移一次到抽奖精灵", 0.60),
            ("a", "抽奖精灵", 1.30),
        ]
        self.on_log("车辆熟练度固定序列：A -> 右 -> A -> 上 -> A -> 上 -> A -> 上 -> A -> 左 -> A。")
        pad.neutral()
        if not self._sleep(0.60):
            return False
        for index, (button, label, delay) in enumerate(steps, start=1):
            if self._stop.is_set():
                return False
            self.on_log(f"车辆熟练度固定序列 {index}/{len(steps)}：{label}，按 {self._move_label(button)}。")
            self._invalidate_ocr()
            pad.tap(button, hold=0.18)
            self._invalidate_ocr()
            if button == "a":
                if not self._sleep_and_watch_mastery_after_a(delay):
                    return False
            elif not self._sleep(delay):
                return False
        return self._confirm_wheelspin_mastery()

    def _sleep_and_watch_mastery_after_a(self, total_seconds):
        # A on the 22B mastery grid can open the "not enough skill points" modal.
        # Check immediately here so the following fixed-sequence directions do not
        # accidentally close the modal before the combo runner can take over.
        deadline = time.monotonic() + max(total_seconds, 0.75)
        wait = 0.25
        while time.monotonic() < deadline and not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if not self._sleep(min(wait, max(0.05, remaining))):
                return False
            self._invalidate_ocr()
            try:
                detection = self.detect_once()
            except Exception as exc:
                self.logger.warning("Failed to watch mastery A result: %s", exc)
                wait = 0.20
                continue
            if self._is_points_exhausted_detection(detection, include_generic_modal=True):
                self._mark_points_exhausted("车辆熟练度：A 后检测到技术点数不足弹窗，停止固定序列。")
                return False
            wait = 0.20
        return not self._stop.is_set()

    def _confirm_wheelspin_mastery(self):
        saw_non_purchase_modal = False
        for attempt in range(1, 3):
            if not self._sleep(0.65):
                return False
            try:
                detection = self.detect_once()
            except Exception as exc:
                self.logger.warning("Failed to verify wheelspin mastery result: %s", exc)
                self.on_log("车辆熟练度：固定序列已按完，但截图验证失败，先停止，避免错循环。")
                return False
            text = detection.ocr_text or ""
            if self._is_points_exhausted_detection(detection, include_generic_modal=True):
                self._mark_points_exhausted("车辆熟练度：检测到技术点数不足弹窗。")
                return False
            if detection.state == STATE_CONFIRM_MODAL or (
                detection.scores.get("modal_lime", 0.0) >= 0.05
                and detection.scores.get("modal_price_yellow", 0.0) < 0.02
            ):
                saw_non_purchase_modal = True
            if "抽奖精灵" in text:
                self.on_log("车辆熟练度：已确认停在“抽奖精灵”。")
                return True
            preview = text[:90] if text else "无文字"
            self.on_log(f"车辆熟练度：第 {attempt} 次未确认到“抽奖精灵”（OCR：{preview}）。")
        if saw_non_purchase_modal:
            self.points_exhausted = True
            self.stop_reason = "points_exhausted"
            self.on_log("车辆熟练度：固定序列后看到非购买确认弹窗，按技术点数不足处理。")
            return False
        self.on_log("车辆熟练度：固定序列按完但没有确认到“抽奖精灵”，先停止，避免带着错误加点继续循环。")
        return False

    def _is_points_exhausted_detection(self, detection, include_generic_modal=False):
        if detection is None:
            return False
        text = detection.ocr_text or ""
        if detection.state == STATE_SKILL_POINTS_EXHAUSTED:
            return True
        if (
            "不够购买额外加成" in text
            or "技术点数不足" in text
            or "不足以解锁" in text
            or "额外加成" in text
        ):
            return True
        if include_generic_modal and detection.state == STATE_CONFIRM_MODAL:
            return (
                detection.scores.get("modal_lime", 0.0) >= 0.04
                and detection.scores.get("modal_price_yellow", 0.0) < 0.02
            )
        return False

    def _mark_points_exhausted(self, message):
        self.points_exhausted = True
        self.stop_reason = "points_exhausted"
        self.on_log(message)

    @staticmethod
    def _opposite_move(move):
        return {
            "dpad_up": "dpad_down",
            "dpad_down": "dpad_up",
            "dpad_left": "dpad_right",
            "dpad_right": "dpad_left",
        }.get(move, move)

    @staticmethod
    def _move_label(move):
        return {
            "a": "A",
            "b": "B",
            "x": "X",
            "y": "Y",
            "lb": "LB",
            "rb": "RB",
            "start": "Menu",
            "back": "View",
            "dpad_up": "上",
            "dpad_down": "下",
            "dpad_left": "左",
            "dpad_right": "右",
        }.get(move, move)

    @staticmethod
    def _state_label(state):
        labels = {
            STATE_CONFIRM_MODAL: "确认弹窗",
            STATE_CONTROLLER_DISCONNECTED: "控制器未连接弹窗",
            STATE_PURCHASE_CONFIRM: "购买确认弹窗",
            STATE_SEARCH_DIALOG: "搜索/筛选弹窗",
            STATE_PAUSE_MENU: "暂停菜单",
            STATE_PAUSE_CARS: "暂停菜单-车辆页",
            STATE_POST_PURCHASE_VIEW: "新车展示页",
            STATE_VEHICLE_TAB: "车辆页",
            STATE_UPGRADE_MENU: "升级页",
            STATE_SKILL_MASTERY: "车辆熟练度页",
            STATE_SKILL_POINTS_EXHAUSTED: "技能点不足弹窗",
            STATE_BUY_SELL_MENU: "购买与出售页",
            STATE_BUY_SELL_SHOWROOM_READY: "购买与出售页-车展已选中",
            STATE_AUTOSHOW_GRID: "购买车辆页",
            STATE_MANUFACTURER_GRID: "制造商列表",
            STATE_MANUFACTURER_SUBARU_READY: "制造商列表-斯巴鲁已选中",
            STATE_SUBARU_GRID: "斯巴鲁车展",
            STATE_SUBARU_22B_READY: "斯巴鲁 22B 已选中",
            STATE_DESIGN_GRID: "推荐设计页",
            STATE_COLOR_SELECT: "出厂颜色页",
            STATE_CAR_PREVIEW: "车辆预览页",
            STATE_EVENTLAB_FAVORITES: "EventLab 我的收藏",
            STATE_EVENTLAB_RACE_TYPE: "EventLab 比赛类型",
            STATE_EVENTLAB_MY_CARS: "EventLab 我的车辆页",
            STATE_EVENTLAB_MY_CARS_22B_READY: "EventLab 22B 已选中",
            STATE_EVENTLAB_FILTER: "EventLab 车辆筛选",
            STATE_UNKNOWN: "未知画面",
        }
        return labels.get(state, state)
