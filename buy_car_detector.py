"""Screen-state detection for the buy-car portion of the automation."""
from dataclasses import dataclass
import re
import unicodedata


STATE_CONFIRM_MODAL = "buy_confirm_modal"
STATE_CONTROLLER_DISCONNECTED = "buy_controller_disconnected"
STATE_PURCHASE_CONFIRM = "buy_purchase_confirm"
STATE_SEARCH_DIALOG = "search_dialog"
STATE_PAUSE_MENU = "buy_pause_menu"
STATE_PAUSE_CARS = "buy_pause_cars"
STATE_BUY_SELL_MENU = "buy_sell_menu"
STATE_BUY_SELL_SHOWROOM_READY = "buy_sell_showroom_ready"
STATE_AUTOSHOW_GRID = "autoshow_grid"
STATE_MANUFACTURER_GRID = "manufacturer_grid"
STATE_MANUFACTURER_SUBARU_READY = "manufacturer_subaru_ready"
STATE_SUBARU_GRID = "subaru_grid"
STATE_SUBARU_22B_READY = "subaru_22b_ready"
STATE_DESIGN_GRID = "design_grid"
STATE_COLOR_SELECT = "color_select"
STATE_CAR_PREVIEW = "car_preview"
STATE_POST_PURCHASE_VIEW = "post_purchase_view"
STATE_VEHICLE_TAB = "vehicle_tab"
STATE_UPGRADE_MENU = "upgrade_menu"
STATE_SKILL_MASTERY = "skill_mastery"
STATE_UNKNOWN = "unknown"


def _lime(r, g, b):
    return g >= 190 and r >= 135 and b <= 95 and (g - b) >= 120


def _white(r, g, b):
    return r >= 210 and g >= 210 and b >= 210


def _dark(r, g, b):
    return r <= 55 and g <= 55 and b <= 55


def _gray(r, g, b):
    return 70 <= r <= 180 and 70 <= g <= 180 and 70 <= b <= 180


def _teal(r, g, b):
    return 15 <= r <= 95 and 90 <= g <= 190 and 85 <= b <= 190 and g >= r + 35


def _yellow(r, g, b):
    return r >= 210 and g >= 165 and b <= 80


def _pink(r, g, b):
    return r >= 190 and g <= 90 and b >= 120


def _green_tile(r, g, b):
    return 120 <= r <= 210 and g >= 185 and b <= 90


def _blue(r, g, b):
    return r <= 90 and 70 <= g <= 170 and b >= 150


@dataclass
class BuyCarDetection:
    state: str
    confidence: float
    scores: dict
    ocr_text: str = ""


class BuyCarScreenDetector:
    """Detect known screens in the Subaru 22B purchase path."""

    @staticmethod
    def _normalize_text(text):
        text = unicodedata.normalize("NFKC", text or "")
        return re.sub(r"\s+", "", text).upper()

    @classmethod
    def _has_any(cls, text, keywords):
        return any(cls._normalize_text(keyword) in text for keyword in keywords)

    def refine_with_ocr(self, detection, ocr_items, frame=None):
        if not ocr_items:
            return detection

        def item_y(item):
            try:
                return float(getattr(item, "ncy", 0.5))
            except Exception:
                return 0.5

        def item_x(item):
            try:
                return float(getattr(item, "ncx", 0.5))
            except Exception:
                return 0.5

        def raw_for(predicate):
            return " | ".join(item.text for item in ocr_items if predicate(item))

        raw_text = raw_for(lambda _item: True)
        all_text = self._normalize_text(raw_text)
        main_text = self._normalize_text(raw_for(lambda item: item_y(item) >= 0.14))
        upper_text = self._normalize_text(raw_for(lambda item: 0.14 <= item_y(item) <= 0.32))
        mid_text = self._normalize_text(raw_for(lambda item: 0.18 <= item_y(item) <= 0.88))
        bottom_text = self._normalize_text(raw_for(lambda item: item_y(item) >= 0.82))
        scores = dict(detection.scores)
        scores["ocr_used"] = 1.0
        scores["ocr_items"] = float(len(ocr_items))
        scores["ocr_mid_items"] = float(sum(1 for item in ocr_items if 0.18 <= item_y(item) <= 0.88))

        def updated(state, confidence):
            return BuyCarDetection(state, confidence, scores, raw_text)

        def has(text, keywords):
            return self._has_any(text, keywords)

        def median_step(values, default):
            values = sorted(set(round(value, 4) for value in values))
            diffs = [
                values[index + 1] - values[index]
                for index in range(len(values) - 1)
                if values[index + 1] - values[index] >= 0.025
            ]
            if not diffs:
                return default
            diffs.sort()
            return diffs[len(diffs) // 2]

        def cluster_centers(values, tolerance):
            values = sorted(values)
            clusters = []
            for value in values:
                if not clusters or abs(value - clusters[-1][-1]) > tolerance:
                    clusters.append([value])
                else:
                    clusters[-1].append(value)
            return [sum(cluster) / len(cluster) for cluster in clusters]

        def closest_index(value, centers, max_distance):
            if not centers:
                return 0
            best_index, best_center = min(
                enumerate(centers, start=1),
                key=lambda pair: abs(pair[1] - value),
            )
            best_distance = abs(best_center - value)
            return best_index if best_distance <= max_distance else 0

        def lime_ratio(region):
            if frame is None:
                return 0.0
            x1, y1, x2, y2 = region
            x1 = max(0.0, min(1.0, x1))
            y1 = max(0.0, min(1.0, y1))
            x2 = max(x1 + 0.001, min(1.0, x2))
            y2 = max(y1 + 0.001, min(1.0, y2))
            return frame.ratio((x1, y1, x2, y2), _lime, step=3)

        def dark_ratio(region):
            if frame is None:
                return 0.0
            x1, y1, x2, y2 = region
            x1 = max(0.0, min(1.0, x1))
            y1 = max(0.0, min(1.0, y1))
            x2 = max(x1 + 0.001, min(1.0, x2))
            y2 = max(y1 + 0.001, min(1.0, y2))
            return frame.ratio((x1, y1, x2, y2), _dark, step=4)

        def selected_cell_from_items(
            items,
            *,
            default_col_step,
            default_row_step=None,
            fixed_y=None,
            use_dark_fill=False,
        ):
            if frame is None or not items:
                return 0, 0, 0.0, 0.0
            col_step = median_step([item_x(item) for item in items], default_col_step)
            row_step = median_step([item_y(item) for item in items], default_row_step or default_col_step)
            col_centers = cluster_centers([item_x(item) for item in items], col_step * 0.35)
            row_centers = cluster_centers([item_y(item) for item in items], row_step * 0.35)
            best = (0, 0, 0.0, 0.0)
            best_score = 0.0
            seen = set()
            for item in items:
                col = closest_index(item_x(item), col_centers, col_step * 0.55)
                row = closest_index(item_y(item), row_centers, row_step * 0.55)
                if not col or not row or (col, row) in seen:
                    continue
                seen.add((col, row))
                x = item_x(item)
                y = item_y(item)
                if fixed_y:
                    y1, y2 = fixed_y
                else:
                    y1, y2 = y - row_step * 0.44, y + row_step * 0.44
                lime_score = lime_ratio((x - col_step * 0.48, y1, x + col_step * 0.48, y2))
                dark_score = (
                    dark_ratio((x - col_step * 0.43, y - row_step * 0.30, x + col_step * 0.43, y + row_step * 0.30))
                    if use_dark_fill
                    else 0.0
                )
                score = max(lime_score, dark_score if use_dark_fill else 0.0)
                if score > best_score:
                    best = (col, row, lime_score, dark_score)
                    best_score = score
            if use_dark_fill and best[2] < 0.015 and best[3] < 0.30:
                return 0, 0, best[2], best[3]
            if not use_dark_fill and best[2] < 0.015:
                return 0, 0, best[2], best[3]
            return best

        def selected_top_card_from_items(items):
            if frame is None or not items:
                return 0, 0.0
            col_step = median_step([item_x(item) for item in items], 0.18)
            col_centers = cluster_centers([item_x(item) for item in items], col_step * 0.35)
            best_col = 0
            best_score = 0.0
            for col, x in enumerate(col_centers, start=1):
                x1 = max(0.0, x - col_step * 0.62)
                x2 = min(1.0, x + col_step * 0.62)
                y1, y2 = 0.195, 0.47
                whole = lime_ratio((x1, y1, x2, y2))
                top = lime_ratio((x1, y1, x2, y1 + 0.025))
                bottom = lime_ratio((x1, y2 - 0.025, x2, y2))
                left = lime_ratio((x1, y1, x1 + 0.018, y2))
                right = lime_ratio((x2 - 0.018, y1, x2, y2))
                edge = max(top, bottom, left, right)
                score = whole + edge * 0.20
                scores[f"subaru_card{col}_whole_lime"] = whole
                scores[f"subaru_card{col}_edge_lime"] = edge
                scores[f"subaru_card{col}_select_score"] = score
                if score > best_score:
                    best_col = col
                    best_score = score
            if best_score < 0.010:
                return 0, best_score
            return best_col, best_score

        autoshow_brand_keywords = [
            "ABARTH",
            "ALUMICRAFT",
            "AMGTRANSPORT",
            "ARIEL",
            "AUSTIN-HEALEY",
            "AUSTIN",
        ]
        subaru_card_keywords = ["BRZ", "WRX", "SVX", "LEGACY", "VIVIO", "IMPREZA22B", "IMPREZAWRX"]
        manufacturer_keywords = [
            "制造商",
            "SHELBY",
            "SIERRACARS",
            "TVR",
            "ULTIMA",
            "ZENVO",
            "保时捷",
        ]

        pause_purchase_seen = has(main_text, ["购买新车与二手车"]) or (
            has(main_text, ["购买新车"]) and has(main_text, ["二手车"])
        )
        autoshow_grid_seen = has(all_text, ["购买车辆"]) and has(mid_text, autoshow_brand_keywords)

        manufacturer_items = [
            item
            for item in ocr_items
            if 0.22 <= item_y(item) <= 0.86
            and 0.10 <= item_x(item) <= 0.90
            and not has(self._normalize_text(item.text), ["制造商", "选择", "取消", "BACKSPACE", "ENTER"])
        ]
        manufacturer_col_step = median_step([item_x(item) for item in manufacturer_items], 0.18)
        manufacturer_row_step = median_step([item_y(item) for item in manufacturer_items], 0.05)
        manufacturer_cols = cluster_centers([item_x(item) for item in manufacturer_items], manufacturer_col_step * 0.35)
        manufacturer_rows = cluster_centers([item_y(item) for item in manufacturer_items], manufacturer_row_step * 0.35)
        manufacturer_target_col = 0
        manufacturer_target_row = 0
        for item in manufacturer_items:
            text = self._normalize_text(item.text)
            if not has(text, ["斯巴鲁", "SUBARU"]):
                continue
            manufacturer_target_col = closest_index(item_x(item), manufacturer_cols, manufacturer_col_step * 0.60)
            manufacturer_target_row = closest_index(item_y(item), manufacturer_rows, manufacturer_row_step * 0.60)
            break
        (
            manufacturer_selected_col,
            manufacturer_selected_row,
            manufacturer_selected_lime,
            manufacturer_selected_dark,
        ) = selected_cell_from_items(
            manufacturer_items,
            default_col_step=0.18,
            default_row_step=0.05,
            use_dark_fill=True,
        )

        subaru_top_items = [
            item
            for item in ocr_items
            if 0.18 <= item_y(item) <= 0.30
            and 0.18 <= item_x(item) <= 0.96
            and not has(self._normalize_text(item.text), ["购买车辆", "LB", "RB"])
        ]
        subaru_col_step = median_step([item_x(item) for item in subaru_top_items], 0.18)
        subaru_cols = cluster_centers([item_x(item) for item in subaru_top_items], subaru_col_step * 0.35)
        subaru_22b_target_text_seen = any(
            (
                0.18 <= item_x(item) <= 0.96
                and 0.18 <= item_y(item) <= 0.30
                and has(self._normalize_text(item.text), ["22B", "2B-STI", "2B-ST1", "IMPREZA22"])
                and has(self._normalize_text(item.text), ["IMPREZA", "STI", "ST1"])
            )
            for item in ocr_items
        )
        subaru_22b_target_col = 0
        for item in ocr_items:
            text = self._normalize_text(item.text)
            if not (
                0.18 <= item_y(item) <= 0.30
                and 0.18 <= item_x(item) <= 0.96
                and has(text, ["22B", "2B-STI", "2B-ST1", "IMPREZA22"])
                and has(text, ["IMPREZA", "STI", "ST1"])
            ):
                continue
            subaru_22b_target_col = closest_index(item_x(item), subaru_cols, subaru_col_step * 0.65)
            if subaru_22b_target_col:
                break
        subaru_selected_col, subaru_selected_lime = selected_top_card_from_items(subaru_top_items)
        subaru_grid_seen = (
            has(all_text, ["购买车辆"])
            and has(mid_text, ["SUBARU", "斯巴鲁", "IMPREZA"])
            and has(mid_text, subaru_card_keywords)
        ) or (
            detection.state in (STATE_SUBARU_GRID, STATE_SUBARU_22B_READY)
            and has(mid_text, ["SUBARU", "斯巴鲁", "IMPREZA"])
            and (has(mid_text, subaru_card_keywords) or subaru_22b_target_text_seen)
        )
        scores["ocr_pause_purchase_seen"] = 1.0 if pause_purchase_seen else 0.0
        scores["ocr_buy_sell_showroom_seen"] = 1.0 if has(main_text, ["车展"]) else 0.0
        scores["ocr_autoshow_grid_seen"] = 1.0 if autoshow_grid_seen else 0.0
        scores["ocr_manufacturer_hint_seen"] = 1.0 if has(all_text, ["前往制造商", "制造商", "BACKSPACE"]) else 0.0
        scores["ocr_manufacturer_subaru_seen"] = 1.0 if has(mid_text, ["斯巴鲁", "SUBARU"]) else 0.0
        scores["ocr_manufacturer_target_col"] = float(manufacturer_target_col)
        scores["ocr_manufacturer_target_row"] = float(manufacturer_target_row)
        scores["ocr_manufacturer_selected_col"] = float(manufacturer_selected_col)
        scores["ocr_manufacturer_selected_row"] = float(manufacturer_selected_row)
        scores["manufacturer_selected_lime"] = manufacturer_selected_lime
        scores["manufacturer_selected_dark"] = manufacturer_selected_dark
        scores["ocr_manufacturer_bottom_seen"] = 1.0 if has(
            mid_text,
            ["沃尔沃", "五菱", "现代", "雪佛兰", "斯巴鲁", "漂移方程式", "日产", "三菱"],
        ) else 0.0
        scores["ocr_subaru_grid_seen"] = 1.0 if subaru_grid_seen else 0.0
        selected_target_lime = (
            subaru_selected_lime
            if subaru_22b_target_col and subaru_selected_col == subaru_22b_target_col
            else scores.get(f"subaru_top_card{subaru_22b_target_col}_lime", 0.0)
            if subaru_22b_target_col
            else 0.0
        )
        scores["ocr_subaru_selected_col"] = float(subaru_selected_col)
        scores["subaru_selected_lime"] = subaru_selected_lime
        scores["subaru_22b_selected_lime"] = selected_target_lime
        scores["ocr_subaru_22b_target_text_seen"] = 1.0 if subaru_22b_target_text_seen else 0.0
        scores["ocr_subaru_22b_target_col"] = float(subaru_22b_target_col)
        scores["ocr_subaru_22b_selected_seen"] = 1.0 if (
            subaru_22b_target_col and selected_target_lime >= 0.025
        ) else 0.0
        scores["ocr_vehicle_upgrade_seen"] = 1.0 if has(mid_text, ["升级与调校"]) else 0.0
        scores["ocr_upgrade_mastery_seen"] = 1.0 if has(mid_text, ["车辆熟练度"]) else 0.0
        pause_cars_tile_seen = pause_purchase_seen or has(mid_text, ["更换车辆", "购买新车", "二手车"])
        vehicle_tab_seen = has(mid_text, ["我的车辆", "升级与调校"]) or (
            not pause_cars_tile_seen
            and has(upper_text, ["车辆"])
            and has(mid_text, ["设计与喷漆", "牌照", "车房宝物", "秘藏座驾"])
        )

        if has(all_text, ["控制器未连接", "重新连接控制器"]):
            return updated(STATE_CONTROLLER_DISCONNECTED, 0.98)

        if has(main_text, ["搜寻"]) and has(main_text, ["关键词", "创建者", "共享代码", "输入文本"]):
            return updated(STATE_SEARCH_DIALOG, 0.94)

        if (
            has(main_text, ["购买车辆"])
            and not has(mid_text, autoshow_brand_keywords + subaru_card_keywords)
            and has(main_text, ["是否要花费", "购买此车辆", "车展车辆票券"])
        ):
            return updated(STATE_PURCHASE_CONFIRM, 0.94)

        if has(main_text, ["移动至嘉年华", "重新开始赛事", "是否要快速移动", "所有未保存"]):
            return updated(STATE_CONFIRM_MODAL, 0.98)

        if pause_cars_tile_seen:
            return updated(STATE_PAUSE_CARS, 0.94)

        if vehicle_tab_seen:
            return updated(STATE_VEHICLE_TAB, 0.94)

        if has(mid_text, ["收集簿", "世界地图", "下一站", "欢迎来到", "FESTIVALPLAYLIST"]):
            return updated(STATE_PAUSE_MENU, 0.92)

        if has(main_text, ["购买与出售"]) and has(mid_text, ["车展"]):
            return updated(STATE_BUY_SELL_SHOWROOM_READY, 0.94)
        if has(main_text, ["购买与出售", "拍卖场", "车辆通行证", "票券车辆"]):
            return updated(STATE_BUY_SELL_MENU, 0.88)

        if autoshow_grid_seen:
            return updated(STATE_AUTOSHOW_GRID, max(0.92, detection.confidence))

        manufacturer_ready_by_color = (
            manufacturer_target_col
            and manufacturer_target_row
            and manufacturer_selected_col == manufacturer_target_col
            and manufacturer_selected_row == manufacturer_target_row
            and (
                scores.get("manufacturer_selected_lime", 0.0) >= 0.015
                or scores.get("manufacturer_selected_dark", 0.0) >= 0.30
            )
        )
        if has(upper_text, ["制造商"]) or (
            not has(main_text, ["购买车辆"]) and has(mid_text, manufacturer_keywords)
        ):
            if manufacturer_ready_by_color and manufacturer_target_col:
                return updated(STATE_MANUFACTURER_SUBARU_READY, max(0.92, detection.confidence))
            return updated(STATE_MANUFACTURER_GRID, 0.88)

        if subaru_grid_seen:
            if scores.get("ocr_subaru_22b_selected_seen", 0.0) >= 0.5:
                return updated(STATE_SUBARU_22B_READY, max(0.90, detection.confidence))
            return updated(STATE_SUBARU_GRID, 0.88)

        if has(main_text, ["推荐设计", "出厂颜色", "颜色", "设计"]):
            if has(main_text, ["出厂颜色"]):
                return updated(STATE_COLOR_SELECT, 0.88)
            return updated(STATE_DESIGN_GRID, 0.88)

        if has(main_text, ["隐藏界面", "驾驶", "拍照模式", "切换视角高度"]):
            return updated(STATE_POST_PURCHASE_VIEW, 0.92)

        if (
            has(main_text, ["更改视角"])
            and has(bottom_text, ["选择"])
            and (scores.get("preview_price_yellow", 0.0) >= 0.20 or has(main_text, ["CR", "@", "86,000", "125,000"]))
        ):
            return updated(STATE_CAR_PREVIEW, 0.88)

        if has(main_text, ["购买车辆"]) and has(main_text, ["购买", "车展车辆票券"]):
            return updated(STATE_PURCHASE_CONFIRM, 0.94)

        if not pause_cars_tile_seen and has(mid_text, ["升级与调校", "我的车辆", "设计与喷漆", "牌照", "汽车喇叭", "秘藏座驾"]):
            return updated(STATE_VEHICLE_TAB, 0.90)

        if has(main_text, ["升级"]) and has(mid_text, ["车辆熟练度", "自动升级", "自定义升级"]):
            return updated(STATE_UPGRADE_MENU, 0.90)

        if has(main_text, ["车辆熟练度", "可用点数", "吸引眼球", "抽奖精灵"]):
            return updated(STATE_SKILL_MASTERY, 0.94)

        if detection.ocr_text:
            return detection
        return BuyCarDetection(detection.state, detection.confidence, scores, raw_text)

    def detect(self, frame):
        scores = {
            "modal_lime": frame.ratio((0.31, 0.39, 0.69, 0.50), _lime, step=5),
            "modal_dark": frame.ratio((0.31, 0.49, 0.69, 0.66), _dark, step=7),
            "modal_white_option": frame.ratio((0.31, 0.58, 0.69, 0.68), _white, step=5),
            "modal_price_yellow": frame.ratio((0.02, 0.80, 0.22, 0.94), _yellow, step=7),
            "disconnect_lime": frame.ratio((0.31, 0.43, 0.69, 0.56), _lime, step=5),
            "disconnect_mid": frame.ratio((0.31, 0.50, 0.69, 0.64), _gray, step=7),
            "pause_teal": frame.ratio((0.02, 0.07, 0.98, 0.90), _teal, step=12),
            "pause_tabs_white": frame.ratio((0.12, 0.18, 0.88, 0.28), _white, step=9),
            "pause_tabs_lime": frame.ratio((0.12, 0.18, 0.88, 0.28), _lime, step=5),
            "pause_cars_tab_lime": frame.ratio((0.34, 0.20, 0.42, 0.28), _lime, step=5),
            "pause_purchase_green": frame.ratio((0.12, 0.30, 0.28, 0.80), _green_tile, step=8),
            "pause_purchase_focus_top_lime": frame.ratio((0.12, 0.240, 0.28, 0.252), _lime, step=3),
            "pause_purchase_focus_bottom_lime": frame.ratio((0.12, 0.785, 0.28, 0.798), _lime, step=3),
            "pause_tuning_pink": frame.ratio((0.72, 0.30, 0.90, 0.80), _pink, step=8),
            "buy_sell_tabs_white": frame.ratio((0.03, 0.18, 0.42, 0.24), _white, step=7),
            "buy_sell_left_dark": frame.ratio((0.03, 0.60, 0.24, 0.88), _dark, step=8),
            "buy_sell_showroom_lime": frame.ratio((0.03, 0.63, 0.24, 0.70), _lime, step=4),
            "buy_sell_other_lime": frame.ratio((0.03, 0.70, 0.24, 0.88), _lime, step=4),
            "vehicle_tabs_white": frame.ratio((0.06, 0.17, 0.94, 0.24), _white, step=8),
            "vehicle_cards_white": frame.ratio((0.20, 0.23, 0.92, 0.88), _white, step=10),
            "vehicle_dark_bg": frame.ratio((0.00, 0.20, 1.00, 0.94), _dark, step=12),
            "subaru_logo_blue": frame.ratio((0.06, 0.24, 0.20, 0.42), _blue, step=5),
            "subaru_logo_white": frame.ratio((0.06, 0.24, 0.20, 0.42), _white, step=5),
            "subaru_top_card1_lime": frame.ratio((0.20, 0.22, 0.40, 0.47), _lime, step=4),
            "subaru_top_card2_lime": frame.ratio((0.39, 0.22, 0.57, 0.47), _lime, step=4),
            "subaru_top_card3_lime": frame.ratio((0.56, 0.22, 0.74, 0.47), _lime, step=4),
            "subaru_top_card4_lime": frame.ratio((0.72, 0.22, 0.91, 0.47), _lime, step=4),
            "subaru_first_car_lime": frame.ratio((0.20, 0.22, 0.40, 0.47), _lime, step=4),
            "subaru_22b_lime": frame.ratio((0.72, 0.22, 0.91, 0.47), _lime, step=4),
            "manufacturer_header_lime": frame.ratio((0.12, 0.20, 0.88, 0.28), _lime, step=6),
            "manufacturer_grid_white": frame.ratio((0.12, 0.28, 0.88, 0.84), _white, step=8),
            "manufacturer_subaru_lime": frame.ratio((0.67, 0.74, 0.88, 0.82), _lime, step=4),
            "design_left_dark": frame.ratio((0.04, 0.22, 0.20, 0.86), _dark, step=8),
            "design_cards_white": frame.ratio((0.20, 0.21, 0.90, 0.88), _white, step=9),
            "design_selected_lime": frame.ratio((0.19, 0.20, 0.38, 0.45), _lime, step=4),
            "color_header_lime": frame.ratio((0.04, 0.17, 0.22, 0.23), _lime, step=4),
            "color_selected_blue": frame.ratio((0.04, 0.27, 0.22, 0.35), _blue, step=5),
            "color_list_dark": frame.ratio((0.04, 0.34, 0.22, 0.88), _dark, step=8),
            "preview_price_yellow": frame.ratio((0.03, 0.82, 0.22, 0.93), _yellow, step=5),
            "preview_dark_bg": frame.ratio((0.00, 0.15, 1.00, 0.82), _dark, step=12),
            "preview_modal_lime": frame.ratio((0.31, 0.39, 0.69, 0.50), _lime, step=5),
            "post_purchase_hints": frame.ratio((0.03, 0.90, 0.65, 0.98), _white, step=7),
            "post_purchase_icon_gray": frame.ratio((0.45, 0.55, 0.55, 0.72), _gray, step=6),
            "vehicle_tab_lime": frame.ratio((0.24, 0.19, 0.32, 0.24), _lime, step=4),
            "vehicle_left_white": frame.ratio((0.03, 0.52, 0.25, 0.88), _white, step=7),
            "vehicle_left_lime": frame.ratio((0.03, 0.52, 0.25, 0.60), _lime, step=4),
            "upgrade_title_dark": frame.ratio((0.03, 0.18, 0.24, 0.25), _dark, step=6),
            "upgrade_list_white": frame.ratio((0.03, 0.46, 0.24, 0.87), _white, step=7),
            "upgrade_selected_lime": frame.ratio((0.03, 0.50, 0.24, 0.58), _lime, step=4),
            "mastery_title_dark": frame.ratio((0.15, 0.15, 0.36, 0.22), _dark, step=6),
            "mastery_grid_dark": frame.ratio((0.15, 0.22, 0.42, 0.90), _dark, step=8),
            "mastery_skill_lime": frame.ratio((0.15, 0.62, 0.42, 0.68), _lime, step=4),
            "mastery_points_yellow": frame.ratio((0.35, 0.84, 0.42, 0.91), _yellow, step=4),
        }
        scores["pause_purchase_focus_lime"] = min(
            scores["pause_purchase_focus_top_lime"],
            scores["pause_purchase_focus_bottom_lime"],
        )

        if (
            scores["disconnect_lime"] >= 0.16
            and scores["modal_white_option"] < 0.03
            and scores["modal_price_yellow"] < 0.02
            and scores["pause_tabs_white"] < 0.05
        ):
            return BuyCarDetection(
                STATE_CONTROLLER_DISCONNECTED,
                min(0.99, scores["disconnect_lime"] * 2),
                scores,
            )

        if (
            scores["modal_lime"] >= 0.08
            and scores["modal_dark"] >= 0.18
            and scores["modal_white_option"] >= 0.09
        ):
            if scores["modal_price_yellow"] >= 0.035:
                return BuyCarDetection(STATE_PURCHASE_CONFIRM, min(0.99, scores["modal_lime"] * 5), scores)
            return BuyCarDetection(STATE_CONFIRM_MODAL, min(0.98, scores["modal_lime"] * 5), scores)

        if (
            scores["mastery_title_dark"] >= 0.75
            and scores["mastery_grid_dark"] >= 0.48
            and scores["mastery_skill_lime"] >= 0.22
            and scores["mastery_points_yellow"] >= 0.10
        ):
            return BuyCarDetection(STATE_SKILL_MASTERY, 0.95, scores)

        if (
            scores["upgrade_title_dark"] >= 0.75
            and scores["upgrade_list_white"] >= 0.42
            and scores["vehicle_tabs_white"] < 0.12
            and scores["mastery_skill_lime"] < 0.08
        ):
            return BuyCarDetection(STATE_UPGRADE_MENU, 0.90, scores)

        if (
            scores["vehicle_tab_lime"] >= 0.05
            and scores["vehicle_left_white"] >= 0.40
            and scores["pause_tabs_white"] >= 0.15
        ):
            return BuyCarDetection(STATE_VEHICLE_TAB, min(0.92, scores["vehicle_left_white"] * 2), scores)

        if scores["color_header_lime"] >= 0.20 and scores["color_selected_blue"] >= 0.35 and scores["color_list_dark"] >= 0.55:
            return BuyCarDetection(STATE_COLOR_SELECT, min(0.96, scores["color_selected_blue"] * 2), scores)

        if (
            scores["design_left_dark"] >= 0.55
            and scores["design_cards_white"] >= 0.45
            and scores["design_selected_lime"] >= 0.04
            and scores["vehicle_tabs_white"] < 0.22
        ):
            return BuyCarDetection(STATE_DESIGN_GRID, min(0.95, scores["design_cards_white"] * 2), scores)

        if (
            scores["post_purchase_hints"] >= 0.12
            and (scores["post_purchase_icon_gray"] >= 0.10 or scores["preview_dark_bg"] >= 0.30)
            and scores["preview_price_yellow"] < 0.06
            and scores["vehicle_tabs_white"] < 0.12
        ):
            return BuyCarDetection(STATE_POST_PURCHASE_VIEW, 0.82, scores)

        if (
            scores["post_purchase_hints"] >= 0.45
            and scores["preview_price_yellow"] < 0.06
            and scores["preview_modal_lime"] < 0.03
            and scores["modal_lime"] < 0.08
            and scores["pause_teal"] < 0.08
            and scores["buy_sell_tabs_white"] < 0.20
            and scores["vehicle_left_white"] < 0.25
            and scores["upgrade_list_white"] < 0.35
        ):
            return BuyCarDetection(STATE_POST_PURCHASE_VIEW, 0.86, scores)

        if scores["manufacturer_header_lime"] >= 0.16 and scores["manufacturer_grid_white"] >= 0.55:
            if scores["manufacturer_subaru_lime"] >= 0.030:
                return BuyCarDetection(STATE_MANUFACTURER_SUBARU_READY, 0.92, scores)
            return BuyCarDetection(STATE_MANUFACTURER_GRID, min(0.92, scores["manufacturer_grid_white"]), scores)

        if scores["subaru_logo_blue"] >= 0.05 and scores["subaru_logo_white"] >= 0.15 and scores["vehicle_cards_white"] >= 0.32:
            if scores["subaru_22b_lime"] >= 0.025:
                return BuyCarDetection(STATE_SUBARU_22B_READY, 0.90, scores)
            return BuyCarDetection(STATE_SUBARU_GRID, 0.86, scores)

        if scores["vehicle_tabs_white"] >= 0.35 and scores["vehicle_cards_white"] >= 0.26 and scores["vehicle_dark_bg"] >= 0.25:
            return BuyCarDetection(STATE_AUTOSHOW_GRID, min(0.90, scores["vehicle_cards_white"] * 2), scores)

        if (
            scores["preview_price_yellow"] >= 0.28
            and scores["preview_dark_bg"] >= 0.36
            and scores["preview_modal_lime"] < 0.03
            and scores["vehicle_tabs_white"] < 0.45
            and scores["vehicle_cards_white"] < 0.32
        ):
            return BuyCarDetection(STATE_CAR_PREVIEW, min(0.95, scores["preview_price_yellow"] * 2), scores)

        if scores["buy_sell_tabs_white"] >= 0.22 and scores["buy_sell_left_dark"] >= 0.35:
            if scores["buy_sell_showroom_lime"] >= 0.035:
                return BuyCarDetection(STATE_BUY_SELL_SHOWROOM_READY, 0.90, scores)
            if scores["buy_sell_other_lime"] >= 0.020:
                return BuyCarDetection(STATE_BUY_SELL_MENU, 0.78, scores)
            return BuyCarDetection(STATE_BUY_SELL_MENU, 0.65, scores)

        pause_like = (
            scores["pause_teal"] >= 0.12
            and (
                scores["pause_tabs_white"] >= 0.10
                or scores["pause_tabs_lime"] >= 0.006
                or scores["pause_cars_tab_lime"] >= 0.020
            )
        )
        if pause_like:
            if (
                scores["pause_cars_tab_lime"] >= 0.020
                and (
                    scores["vehicle_cards_white"] >= 0.08
                    or scores["pause_purchase_green"] >= 0.010
                    or scores["pause_tuning_pink"] >= 0.010
                )
            ):
                return BuyCarDetection(STATE_PAUSE_CARS, 0.88, scores)
            return BuyCarDetection(STATE_PAUSE_MENU, 0.78, scores)

        return BuyCarDetection(STATE_UNKNOWN, 0.0, scores)
