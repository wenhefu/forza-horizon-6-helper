from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata
from typing import Iterable

from v3.frame_utils import frame_to_pil
from v3.types import clamp_bbox


MANUFACTURER_NAMES = (
    "ABARTH",
    "ALUMICRAFT",
    "AMG",
    "ARIEL",
    "AUSTIN-HEALEY",
    "AUTOZAM",
    "BAC",
    "CAN-AM",
    "DEBERTI",
    "DELOREAN",
    "GMC",
    "HOLDEN",
    "HSV",
    "JEEP",
    "KTM",
    "MINI",
    "PLYMOUTH",
    "RAM",
    "RELIANT",
    "RIVIAN",
    "SHELBY",
    "SUBARU",
    "TVR",
    "ULTIMA",
    "ZENVO",
    "奥迪",
    "宝马",
    "保时捷",
    "本田",
    "标致",
    "别克",
    "宾利",
    "达特桑",
    "大众",
    "道奇",
    "法拉利",
    "丰田",
    "福特",
    "捷豹",
    "凯迪拉克",
    "科尼塞格",
    "兰博基尼",
    "蓝旗亚",
    "雷克萨斯",
    "雷诺",
    "莲花",
    "路虎",
    "马自达",
    "玛莎拉蒂",
    "迈凯伦",
    "梅赛德斯",
    "帕加尼",
    "庞蒂亚克",
    "讴歌",
    "欧宝",
    "漂移方程式",
    "日产",
    "三菱",
    "斯巴鲁",
    "沃尔沃",
    "五菱",
    "现代",
    "雪佛兰",
)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", "", text).upper()


def has_any(normalized_text: str, keywords) -> bool:
    return any(normalize_text(keyword) in normalized_text for keyword in keywords)


@dataclass(frozen=True)
class ControlHint:
    action: str
    label: str
    buttons: tuple[str, ...] = ()
    raw: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["buttons"] = list(self.buttons)
        return data


@dataclass(frozen=True)
class ScrollState:
    visible: bool = False
    orientation: str = "vertical"
    position: str = "unknown"
    can_scroll_up: bool = False
    can_scroll_down: bool = False
    track_bbox: tuple[float, float, float, float] | None = None
    thumb_bbox: tuple[float, float, float, float] | None = None
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "visible": self.visible,
            "orientation": self.orientation,
            "position": self.position,
            "can_scroll_up": self.can_scroll_up,
            "can_scroll_down": self.can_scroll_down,
            "track_bbox": list(self.track_bbox) if self.track_bbox else None,
            "thumb_bbox": list(self.thumb_bbox) if self.thumb_bbox else None,
            "source": self.source,
        }


CONTROL_PATTERNS = (
    ("select", "选择/确定", ("A", "Enter"), ("A选择", "ENTER选择", "ENTER确定", "选择", "确定")),
    ("back", "返回/取消", ("B", "Esc"), ("B返回", "ESC返回", "返回", "取消")),
    ("sort", "排序", ("X",), ("X排序", "排序")),
    ("creator_info", "创建者信息", ("X",), ("X创建者信息", "创建者信息")),
    ("change_view", "更改视角", ("X",), ("X更改视角", "更改视角")),
    ("filter", "筛选", ("Y",), ("Y筛选", "筛选")),
    ("color", "颜色", ("Y",), ("Y颜色", "颜色")),
    ("favorite_event", "最爱的赛事/切换收藏", ("Y",), ("Y最爱的赛事", "最爱的赛事", "Y移除最爱", "移除最爱", "添加至收藏")),
    ("buy_voucher", "购买车展车辆票券", ("Space",), ("SPACE购买车展车辆票券", "购买车展车辆票券", "车展车辆票券")),
    ("event_options", "赛事选项", ("Space",), ("SPACE赛事选项", "赛事选项")),
    ("manufacturer", "前往制造商", ("Back/View", "Backspace"), ("BACKSPACE前往制造商", "前往制造商")),
    ("search", "搜寻/搜索", ("Backspace",), ("BACKSPACE搜寻", "BACKSPACE搜索", "搜寻", "搜索")),
    ("toggle_details", "切换详情", ("P",), ("P切换详情", "切换详情")),
    ("event_info", "查看赛事信息", ("P",), ("P查看赛事信息", "查看赛事信息")),
    ("toggle_data", "切换数据", ("L",), ("L切换数据", "切换数据")),
    ("previous_tab", "上一分页", ("LB",), ("LB", "上一分页")),
    ("next_tab", "下一分页", ("RB",), ("RB", "下一分页")),
)


def parse_control_hints(text: str) -> list[ControlHint]:
    normalized = normalize_text(text)
    hints: list[ControlHint] = []
    for action, label, buttons, patterns in CONTROL_PATTERNS:
        if has_any(normalized, patterns):
            hints.append(ControlHint(action=action, label=label, buttons=buttons, raw=text))
    return hints


def parse_control_hints_from_items(items: Iterable) -> list[ControlHint]:
    bottom_text = " | ".join(str(getattr(item, "text", "") or "") for item in items or [] if float(getattr(item, "ncy", 0.0) or 0.0) >= 0.80)
    return parse_control_hints(bottom_text)


EVENTLAB_CARD_DECORATIVE = {
    "",
    "EVENTLAB",
    "HORIZON",
    "HORIZONEVENTLAB",
    "HORZON",
    "HORZONLAB",
    "ANYTHING",
    "GOES",
    "GOESH",
    "TOTAL",
    "AWD",
    "DRIFT",
    "CARS",
    "巨献",
    "已献",
    "已收藏",
    "我的收藏",
    "我的历史记录",
    "最爱的创作者",
    "精选",
    "热门",
    "本月最佳",
    "最新最热",
    "全新",
}


def eventlab_event_title(text: str) -> str:
    parts = [part.strip(" -:，,。!？?[]()（）") for part in str(text or "").replace("\n", "|").split("|")]
    normalized_parts = [normalize_text(part) for part in parts]
    start_index = 0
    for index, normalized in enumerate(normalized_parts):
        if "EVENTLAB" in normalized:
            start_index = index + 1
            break

    title_parts: list[str] = []
    for part, normalized in zip(parts[start_index:], normalized_parts[start_index:]):
        if not part:
            continue
        if normalized in EVENTLAB_CARD_DECORATIVE:
            if title_parts:
                break
            continue
        if _looks_like_event_metric(normalized) or _looks_like_creator_name(normalized):
            continue
        if normalized in {"冒险", "柏油路", "高速道路", "技术", "倾斜弯道", "顺滑"}:
            continue
        if len(normalized) <= 1:
            continue
        title_parts.append(part)
        if len(title_parts) >= 3:
            break

    title = " ".join(title_parts).strip()
    title = re.sub(r"(?i)\bSP\s*FARM\b", "SP Farm", title)
    title = re.sub(r"(?i)^SPFARM", "SP Farm", title)
    title = re.sub(r"\s*/\s*", " / ", title)
    title = re.sub(r"\s+", " ", title)
    return title[:120]


def _looks_like_event_metric(normalized: str) -> bool:
    if not normalized:
        return True
    if re.fullmatch(r"[\d,，.]+", normalized):
        return True
    if re.fullmatch(r"[\d,.]+(千米|干米|KM|MI)", normalized):
        return True
    if re.fullmatch(r"[\d,，.]+[♡❤♥]?", normalized):
        return True
    return False


def _looks_like_creator_name(normalized: str) -> bool:
    if not normalized:
        return False
    if re.fullmatch(r"[A-Z0-9_]{6,18}", normalized):
        return True
    return False


def detect_eventlab_filter_state(frame, ocr_items=None) -> dict:
    if frame is None:
        return {}
    try:
        from v3.focus_regions import find_lime_focus_boxes
    except Exception:
        return {}

    boxes = find_lime_focus_boxes(
        frame,
        (0.24, 0.16, 0.76, 0.86),
        min_width=0.20,
        min_height=0.030,
        max_height=0.090,
        min_aspect=4.0,
        max_fill_ratio=0.50,
        max_boxes=3,
    )
    if not boxes:
        return {}

    box = sorted(boxes, key=lambda item: (item.bbox[1], -item.confidence))[0]
    text = _ocr_text_inside_bbox(ocr_items or [], box.bbox)
    focused_row = _filter_row_name(text, box.bbox)
    favorite_checked = None
    checkbox_bbox = None
    checkbox_evidence = {}
    if focused_row == "收藏":
        checkbox_bbox = _favorite_checkbox_bbox(box.bbox)
        checkbox_evidence = _checkbox_evidence(frame, checkbox_bbox)
        favorite_checked = checkbox_evidence.get("checked")

    return {
        "visible": True,
        "focused_row": focused_row,
        "favorite_checked": favorite_checked,
        "focus_bbox": [float(value) for value in clamp_bbox(box.bbox)],
        "checkbox_bbox": [float(value) for value in clamp_bbox(checkbox_bbox)] if checkbox_bbox else None,
        "checkbox_evidence": checkbox_evidence,
        "confidence": float(box.confidence),
        "source": "lime-focus+checkbox",
        "text": text,
    }


def detect_skill_points(ocr_text: str):
    """Available car-mastery skill points from menu OCR, or None if not shown.

    Two surfaces show the count (verified live, FH6 zh-Hans):
      - the Vehicles tab tile:   '18技术点数可用'  (number BEFORE 技术点数)
      - the mastery tree footer: '可用点数' | '18 ('  (number AFTER 可用点数,
        often a separate OCR token, hence the \\D gap)
    The '技术点数不足' (insufficient) popup has no number -> returns None, leaving
    that case to the existing skill_points_exhausted screen.
    """
    if not ocr_text:
        return None
    # mastery tree footer: '可用点数 ... N' (most specific, check first)
    match = re.search(r"可用点数\D{0,6}(\d{1,4})", ocr_text)
    if match:
        return int(match.group(1))
    # vehicles-tab tile: 'N技术点数可用' / 'N 技术点数'
    match = re.search(r"(\d{1,4})\s*技[术術]点数", ocr_text)
    if match:
        return int(match.group(1))
    # fallback: '技术点数 ... N'
    match = re.search(r"技[术術]点数\D{0,6}(\d{1,4})", ocr_text)
    if match:
        return int(match.group(1))
    return None


def detect_vehicle_action_menu(ocr_text: str) -> dict:
    """Recognize the per-car '选择操作' popup (A on a car) + read its key state.

    The menu DIFFERS by context (both live-captured):
      - via 拍卖场→开始拍卖: '选择操作 | 拍卖车辆 | 上车 | 添加至收藏 | 查看车辆 |
        查看历史记录 | 从车库移除车辆 | 选择 | 取消'  (拍卖车辆 present, default-focused)
      - via 我的车辆 directly: '选择操作 | 上车 | 添加至收藏 | 查看车辆 | 查看历史记录 |
        从车库移除车辆 | 举报并移除涂装 | 选择 | 取消'  (NO 拍卖车辆; remove-only)
    The favorite option is the reliable per-car safety read: 添加至收藏 => NOT favorited
    (sellable), 从收藏中移除 => favorited (the farm car the nav relies on => PROTECT).
    """
    text = ocr_text or ""
    visible = "选择操作" in text and (
        "拍卖车辆" in text or "从车库移除" in text or "查看车辆" in text
    )
    has_remove = "从车库移除" in text
    # Favorited shows as 从收藏中移除 OR 从我的收藏中移除 -> match the shared substring
    # (a plain "从收藏中移除" check MISSED 从我的收藏中移除 -> would fail to protect a fav car).
    favorited = "收藏中移除" in text
    has_drive = "上车" in text
    return {
        "visible": visible,
        "has_auction": "拍卖车辆" in text,        # auction-path menu (default-focused 拍卖车辆)
        "has_remove": has_remove,                 # 从车库移除车辆 present == the game allows removal
        "has_favorite": "添加至收藏" in text or favorited,
        "favorited": favorited,                    # True => the farm car => NEVER sell
        "has_drive": has_drive,
        # GAME-NATIVE PROTECTION: the currently-DRIVING car's menu has NO 上车 and NO
        # 从车库移除车辆 -- you cannot delete the car you are driving. So has_remove is the
        # primary safety: if it's missing, the game itself refuses to remove this car.
        "is_driving": visible and not has_drive,
        # Safe to sell ONLY if the game offers removal AND the car is not favorited.
        "sellable": has_remove and not favorited,
    }


def detect_remove_confirm(ocr_text: str) -> dict:
    """Recognize the '从车库移除车辆' confirm dialog (user-confirmed screenshot).

    OCR: '从车库移除车辆 | 确定要移除所选车辆吗？ | 不 | 嗯'. Default focus is 不 (No);
    to confirm, DpadDown -> 嗯 -> A. The runner MUST see this exact dialog before pressing
    嗯, so a mis-navigated menu (e.g. landing on 举报并移除涂装) can never confirm a removal.
    """
    text = ocr_text or ""
    visible = "从车库移除" in text and ("确定要移除" in text or "移除所选车辆" in text)
    return {"visible": visible}


# --- Auction house (Phase C) -------------------------------------------------
# The screen classifier mislabels these (autoshow_buy_sell / unknown), so the snipe
# runner uses these standalone OCR detectors instead. Strings captured live (zh-Hans).

def detect_auction_search(ocr_text: str) -> dict:
    """The 搜寻 search-config screen: 车厂/型号/性能等级/车辆类型/最高竞价/最高买断价/确认.
    '最高买断价' is the distinctive field (the snipe's price cap)."""
    text = ocr_text or ""
    visible = "搜寻" in text and ("买断价" in text or "最高竞价" in text)
    return {"visible": visible, "has_buyout_cap": "买断价" in text}


def detect_auction_results(ocr_text: str) -> dict:
    """The 拍卖详情 results LIST screen (after 确认): a column of listing cards + a right
    detail panel. '拍卖详情' is distinctive. Excludes the single-listing detail view
    (车辆详情, see detect_auction_detail), which also carries '拍卖详情' but adds car stats."""
    text = ocr_text or ""
    visible = "拍卖详情" in text and "车辆详情" not in text
    return {"visible": visible, "has_options": "拍卖选项" in text}


def detect_auction_house(ocr_text: str) -> dict:
    """The 拍卖场 landing menu: 搜索拍卖 / 开始拍卖 / 我的竞价 / 我的拍卖 / 拍卖提醒.
    Distinguished from results (拍卖详情) and search (搜寻)."""
    text = ocr_text or ""
    if "拍卖详情" in text or "搜寻" in text:
        return {"visible": False}
    visible = "拍卖场" in text and ("搜索拍卖" in text or "开始拍卖" in text)
    return {"visible": visible}


def detect_buyout_confirm(ocr_text: str) -> dict:
    """The 买断 (Buy Out) confirm popup, and its outcomes. Verified before pressing Yes so
    a mis-navigated menu can never confirm a purchase.

    Must require the confirm-QUESTION shape, NOT just '买断' + a confirm word: the SEARCH
    screen carries '最高买断价' (contains 买断) and a '确认' button, which would false-match.
    Outcome strings (成交/失败...) to refine against real captures live."""
    text = ocr_text or ""
    visible = any(k in text for k in ("确定要买断", "买断吗", "是否买断", "确认买断", "确定买断"))
    return {
        "visible": visible,
        "succeeded": "成交" in text or "购买成功" in text,
        "failed": "失败" in text or "已售出" in text or "出价更高" in text,
    }


def detect_auction_detail(ocr_text: str) -> dict:
    """The single-listing detail screen (车辆详情) reached by 选择/Enter on a results card:
    full car stats + two action rows -- 竞价 (BID, focused by default at the TOP) and 买断
    (BUY OUT, directly BELOW it). The snipe lands here, then presses Down ONCE (竞价 -> 买断).

    Distinguished from the results LIST (also '拍卖详情' + '买断') by the '车辆详情' pager and
    a stat label (马力/扭矩/传动系统/排气量); from the search screen by requiring those stats
    rather than '搜寻'. has_buyout/has_bid say both rows are present (so a Down is meaningful)."""
    text = ocr_text or ""
    has_stats = any(k in text for k in ("马力", "扭矩", "传动系统", "排气量"))
    has_buyout = "买断" in text
    has_bid = "竞价" in text
    visible = (
        "车辆详情" in text and has_stats and has_buyout and has_bid and "搜寻" not in text
    )
    return {"visible": visible, "has_buyout": has_buyout, "has_bid": has_bid}


def detect_bid_confirm(ocr_text: str) -> dict:
    """The 竞价 (BID) confirm popup -- the DANGER screen. The snipe must NEVER confirm here:
    a bid ties up credits and can be outbid; we only ever Buy Out. If a dropped Down on the
    detail screen leaves 竞价 (not 买断) selected, Enter opens THIS dialog -- the runner detects
    it and backs out (B) without pressing 嗯. Shape: 竞价 / 是否确定要为该拍卖竞价 CR N？ /
    如果有人出价高于您...从"我的竞价"取回点数。 / 嗯 / 不."""
    text = ocr_text or ""
    visible = "确定要为该拍卖竞价" in text or ("竞价" in text and "取回点数" in text)
    return {"visible": visible}


def detect_network_warning(ocr_text: str) -> dict:
    """The online-disconnect banner (拍卖场 is an online feature). When shown, buy-outs fail,
    so the snipe treats results as unbuyable (pauses/backs out) instead of pressing into a
    dead dialog. Shape: 注意！ / 连接已断开，请稍后再试 / 返回漫游模式才可接受邀请."""
    text = ocr_text or ""
    visible = "连接已断开" in text or "请稍后再试" in text
    return {"visible": visible}


def detect_buyout_success(ocr_text: str) -> dict:
    """The IMMEDIATE post-buy popup after pressing 嗯 on the 买断 confirm (captured live):
    '买断成功。您可以在“我的竞价”页面领取该车辆' + 确定. This is the buy's success signal --
    the car is paid for and parked in 我的竞价 to be collected later. Press 确定 (A) to clear
    it and return to the results list. Distinct from the 买断 CONFIRM (是否确定要买断)."""
    text = ocr_text or ""
    visible = "买断成功" in text
    return {"visible": visible}


def detect_auction_won(ocr_text: str) -> dict:
    """After a winning buy-out, the listing detail shows '拍卖完成 / 中标' and a 领取车辆
    (collect-vehicle) button. Pressing A on it collects the car into the garage. This is
    NOT a buy/bid action -- the auction is already won and paid -- so collecting is safe."""
    text = ocr_text or ""
    visible = "拍卖完成" in text and ("中标" in text or "领取车辆" in text)
    return {"visible": visible, "can_collect": "领取车辆" in text}


def detect_auction_collected(ocr_text: str) -> dict:
    """The 领取车辆 result popup. done=True only on the success message
    ('您已成功领取本车辆。该车辆已加入您的车库。', press 确定); collecting=True on the transient
    '正在领取您的车辆。请稍候...' loading frame (wait, don't act)."""
    text = ocr_text or ""
    collecting = "正在领取" in text
    done = "已加入您的车库" in text or "已成功领取" in text
    return {"visible": collecting or done, "done": done, "collecting": collecting}


def _ocr_text_inside_bbox(items, bbox) -> str:
    x1, y1, x2, y2 = clamp_bbox(bbox)
    parts = []
    for item in items or []:
        cx = float(getattr(item, "ncx", 0.0) or 0.0)
        cy = float(getattr(item, "ncy", 0.0) or 0.0)
        if x1 - 0.02 <= cx <= x2 + 0.02 and y1 - 0.02 <= cy <= y2 + 0.02:
            parts.append(str(getattr(item, "text", "") or ""))
    return " | ".join(part for part in parts if part)


def _filter_row_name(text: str, bbox) -> str:
    normalized = normalize_text(text)
    if "收藏" in normalized:
        return "收藏"
    if "性能等级" in normalized:
        return "性能等级"
    if "车辆类型" in normalized:
        return "车辆类型"
    if "制造商" in normalized:
        return "制造商"
    _x1, y1, _x2, y2 = clamp_bbox(bbox)
    if (y1 + y2) / 2.0 <= 0.31:
        return "收藏"
    return ""


def _favorite_checkbox_bbox(row_bbox):
    x1, y1, x2, y2 = clamp_bbox(row_bbox)
    row_h = max(0.001, y2 - y1)
    size = min(0.028, max(0.016, row_h * 0.45))
    cx = x2 - row_h * 0.43
    cy = (y1 + y2) / 2.0
    return clamp_bbox((cx - size / 2.0, cy - size / 2.0, cx + size / 2.0, cy + size / 2.0))


def _checkbox_is_checked(frame, bbox) -> bool | None:
    return _checkbox_evidence(frame, bbox).get("checked")


def _checkbox_evidence(frame, bbox) -> dict:
    try:
        import numpy as np

        image = frame_to_pil(frame).convert("RGB")
        width, height = image.size
        x1, y1, x2, y2 = _expanded_bbox(bbox, 1.55)
        crop = image.crop((int(x1 * width), int(y1 * height), int(x2 * width), int(y2 * height)))
        arr = np.asarray(crop)
        if arr.size == 0:
            return {"checked": None, "source": "empty-crop"}
        white = _neutral_light_mask(arr)
        if not bool(white.any()):
            return {"checked": False, "source": "no-white"}
        square = _checkbox_component_bbox(white)
        if square is not None:
            sx1, sy1, sx2, sy2 = square
            square_mask = white[sy1:sy2, sx1:sx2]
            result = _checkbox_tick_present(square_mask)
            if result is not None:
                return {
                    "checked": result,
                    "source": "localized-square",
                    "square": [int(sx1), int(sy1), int(sx2), int(sy2)],
                    "interior_pixels": _checkbox_interior_pixels(square_mask),
                }

        # Fallback: when antialiasing splits the empty square into several
        # components, analyze the expected checkbox area directly.
        x1, y1, x2, y2 = _expanded_bbox(bbox, 1.12)
        crop = image.crop((int(x1 * width), int(y1 * height), int(x2 * width), int(y2 * height)))
        direct = _neutral_light_mask(np.asarray(crop))
        if not bool(direct.any()):
            return {"checked": False, "source": "direct-no-white"}
        result = _checkbox_tick_present(direct)
        return {
            "checked": result,
            "source": "direct",
            "interior_pixels": _checkbox_interior_pixels(direct),
        }
    except Exception:
        return {"checked": None, "source": "error"}


def _neutral_light_mask(arr):
    try:
        import numpy as np
    except Exception:
        return None

    rgb = arr[:, :, :3].astype(np.int16)
    max_channel = rgb.max(axis=2)
    min_channel = rgb.min(axis=2)
    return (
        (rgb[:, :, 0] >= 150)
        & (rgb[:, :, 1] >= 150)
        & (rgb[:, :, 2] >= 150)
        & ((max_channel - min_channel) <= 95)
    )


def _checkbox_tick_present(mask) -> bool | None:
    try:
        import numpy as np
    except Exception:
        return None

    if mask is None:
        return None
    h, w = mask.shape[:2]
    if h < 8 or w < 8:
        return None
    margin = max(2, int(min(h, w) * 0.23))
    if h <= margin * 2 or w <= margin * 2:
        return None
    inner = mask[margin : h - margin, margin : w - margin]
    if inner.size == 0:
        return None
    ys, xs = np.nonzero(inner)
    count = int(len(xs))
    if count < max(3, int(min(h, w) * 0.24)):
        return False

    inner_h, inner_w = inner.shape[:2]
    x_span = (int(xs.max()) - int(xs.min()) + 1) / float(max(1, inner_w))
    y_span = (int(ys.max()) - int(ys.min()) + 1) / float(max(1, inner_h))
    inner_ratio = count / float(inner.size)
    if inner_ratio < 0.025 or x_span < 0.22 or y_span < 0.22:
        return False

    x_norm = xs / float(max(1, inner_w - 1))
    y_norm = ys / float(max(1, inner_h - 1))
    left_lower = bool(((x_norm <= 0.46) & (y_norm >= 0.38)).any())
    right_upper = bool(((x_norm >= 0.44) & (y_norm <= 0.68)).any())
    mid_body = bool(((x_norm >= 0.28) & (x_norm <= 0.78) & (y_norm >= 0.22) & (y_norm <= 0.82)).any())
    if not bool(mid_body and left_lower and right_upper):
        return False

    if count >= 3:
        try:
            corr = float(np.corrcoef(x_norm, y_norm)[0, 1])
        except Exception:
            corr = 0.0
        # A check mark has meaningful interior pixels running from lower-left
        # toward upper-right. Empty square borders can leave stray pixels, but
        # they should not create a strong enough rising stroke.
        if corr > 0.35:
            return False

    return True


def _checkbox_interior_pixels(mask) -> int:
    try:
        import numpy as np
    except Exception:
        return 0
    if mask is None:
        return 0
    h, w = mask.shape[:2]
    margin = max(2, int(min(h, w) * 0.23))
    if h <= margin * 2 or w <= margin * 2:
        return 0
    inner = mask[margin : h - margin, margin : w - margin]
    return int(np.count_nonzero(inner))


def _expanded_bbox(bbox, factor: float):
    x1, y1, x2, y2 = clamp_bbox(bbox)
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    width = max(0.001, (x2 - x1) * factor)
    height = max(0.001, (y2 - y1) * factor)
    return clamp_bbox((cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0))


def _checkbox_component_bbox(mask):
    try:
        import numpy as np
    except Exception:
        return None

    active = mask.astype(bool)
    height, width = active.shape[:2]
    visited = np.zeros_like(active, dtype=bool)
    starts = np.column_stack(np.nonzero(active))
    best = None
    best_score = -1.0
    for start_y, start_x in starts:
        start_y = int(start_y)
        start_x = int(start_x)
        if visited[start_y, start_x]:
            continue
        stack = [(start_x, start_y)]
        visited[start_y, start_x] = True
        min_x = max_x = start_x
        min_y = max_y = start_y
        area = 0
        while stack:
            x, y = stack.pop()
            area += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    if not visited[ny, nx] and active[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((nx, ny))
        box_w = max_x - min_x + 1
        box_h = max_y - min_y + 1
        if box_w < 8 or box_h < 8:
            continue
        aspect = box_w / float(max(1, box_h))
        if not (0.55 <= aspect <= 1.70):
            continue
        fill = area / float(max(1, box_w * box_h))
        if fill > 0.70:
            continue
        score = area - abs(box_w - box_h) * 1.5
        if score > best_score:
            best_score = score
            best = (min_x, min_y, max_x + 1, max_y + 1)
    return best


def looks_like_manufacturer_grid(text: str) -> bool:
    normalized = normalize_text(text)
    if not has_any(normalized, ["制造商"]):
        return False
    hits = manufacturer_hits(normalized)
    return len(hits) >= 4


def looks_like_vehicle_buy_grid(all_text: str, bottom_text: str) -> bool:
    bottom = normalize_text(bottom_text)
    if not has_any(bottom, ["筛选", "排序", "前往制造商", "切换详情", "切换数据", "购买车展车辆票券"]):
        return False
    text = normalize_text(all_text)
    return has_any(text, ["购买车辆", "我的车辆", "已拥有", "IMPREZA", "BRZ", "WRX", "斯巴鲁", "#6165", "CLASS1BUGGY"])


def manufacturer_hits(text: str) -> list[str]:
    normalized = normalize_text(text)
    hits = []
    for name in MANUFACTURER_NAMES:
        if normalize_text(name) in normalized:
            hits.append(name)
    return hits


def infer_manufacturer_scroll_from_text(text: str) -> ScrollState:
    normalized = normalize_text(text)
    hits = set(manufacturer_hits(normalized))
    top_markers = {"ABARTH", "ALUMICRAFT", "ARIEL", "AUSTIN-HEALEY", "AUTOZAM"}
    bottom_markers = {"斯巴鲁", "现代", "雪佛兰", "五菱", "沃尔沃", "日产", "三菱"}
    has_top = bool(hits & top_markers)
    has_bottom = bool(hits & bottom_markers)
    if has_top and not has_bottom:
        return ScrollState(True, position="top", can_scroll_up=False, can_scroll_down=True, source="ocr-manufacturer-names")
    if has_bottom and not has_top:
        return ScrollState(True, position="bottom", can_scroll_up=True, can_scroll_down=False, source="ocr-manufacturer-names")
    if has_top and has_bottom:
        return ScrollState(True, position="mixed", can_scroll_up=True, can_scroll_down=True, source="ocr-manufacturer-names")
    if hits:
        return ScrollState(True, position="middle", can_scroll_up=True, can_scroll_down=True, source="ocr-manufacturer-names")
    return ScrollState(False, source="ocr-manufacturer-names")


def detect_vertical_scrollbar(frame) -> ScrollState:
    if frame is None:
        return ScrollState(False, source="visual-scrollbar")
    try:
        import cv2
        import numpy as np
    except Exception:
        return ScrollState(False, source="visual-scrollbar")

    try:
        image = frame_to_pil(frame).convert("RGB")
        arr = np.asarray(image)
        height, width = arr.shape[:2]
        search = (0.78, 0.14, 0.98, 0.90)
        sx1, sy1, sx2, sy2 = search
        x1 = int(sx1 * width)
        y1 = int(sy1 * height)
        x2 = max(x1 + 1, int(sx2 * width))
        y2 = max(y1 + 1, int(sy2 * height))
        crop = arr[y1:y2, x1:x2]
        if crop.size == 0:
            return ScrollState(False, source="visual-scrollbar")
        r = crop[:, :, 0].astype("int16")
        g = crop[:, :, 1].astype("int16")
        b = crop[:, :, 2].astype("int16")
        bright = (r >= 150) & (g >= 150) & (b >= 150)
        grayish = (abs(r - g) <= 55) & (abs(g - b) <= 55)
        mask = (bright & grayish).astype("uint8")
        if int(mask.sum()) <= 0:
            return ScrollState(False, source="visual-scrollbar")

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 12))
        merged = cv2.dilate(mask, kernel, iterations=1)
        num, _labels, stats, _centroids = cv2.connectedComponentsWithStats(merged, 8)
        best = None
        for index in range(1, num):
            cx, cy, cw, ch, area = stats[index]
            norm_w = cw / float(width)
            norm_h = ch / float(height)
            if norm_h < 0.16 or norm_w > 0.025 or ch / max(cw, 1) < 8:
                continue
            candidate = (area, cx, cy, cw, ch)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if not best:
            return ScrollState(False, source="visual-scrollbar")
        _area, cx, cy, cw, ch = best
        bbox = clamp_bbox(((x1 + cx) / width, (y1 + cy) / height, (x1 + cx + cw) / width, (y1 + cy + ch) / height))
        center_y = (bbox[1] + bbox[3]) / 2.0
        if center_y < 0.42:
            position = "top"
            can_up, can_down = False, True
        elif center_y > 0.66:
            position = "bottom"
            can_up, can_down = True, False
        else:
            position = "middle"
            can_up, can_down = True, True
        return ScrollState(True, position=position, can_scroll_up=can_up, can_scroll_down=can_down, track_bbox=bbox, source="visual-scrollbar")
    except Exception:
        return ScrollState(False, source="visual-scrollbar")


def merge_scroll_states(*states: ScrollState) -> ScrollState:
    visible = [state for state in states if state.visible]
    if not visible:
        return ScrollState(False)
    visual = next((state for state in visible if state.source == "visual-scrollbar"), None)
    text = next((state for state in visible if state.source == "ocr-manufacturer-names"), None)
    if visual and text:
        return ScrollState(
            True,
            orientation=visual.orientation,
            position=text.position if text.position != "unknown" else visual.position,
            can_scroll_up=text.can_scroll_up,
            can_scroll_down=text.can_scroll_down,
            track_bbox=visual.track_bbox,
            thumb_bbox=visual.thumb_bbox,
            source="visual+ocr",
        )
    return visual or text or visible[0]


def canonical_vehicle_name(text: str) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    normalized = normalize_text(raw)
    if not normalized:
        return ""
    if "22B" in normalized and ("IMPREZA" in normalized or "斯巴鲁" in raw):
        return "IMPREZA 22B-STI VERSION"
    if (
        ("IMPREZA" in normalized or "IMPREZ" in normalized)
        and "1998" in normalized
        and ("ERSION" in normalized or "STI" in normalized or "B600" in normalized)
    ):
        return "IMPREZA 22B-STI VERSION"
    if "#6165" in normalized:
        return "#6165 TRICK TRUCK"
    if "#122" in normalized or "CLASS1BUGGY" in normalized:
        return "#122 CLASS 1 BUGGY"
    if normalized.startswith("BRZ"):
        return "BRZ"
    if normalized.startswith("WRXSTI") or "WRXSTI" in normalized:
        return "WRX STI"
    if normalized.startswith("WRX"):
        return "WRX"
    return raw.split("|")[0].strip()
