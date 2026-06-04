from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from v3.buying_ui import normalize_text
from v3.ui_tree import EVENTLAB_TABS, PAUSE_TABS


TARGET_EVENT_KEYWORDS = ("SPFARM", "SKILLPOINT", "SKILLPOINTS", "24SECOND", "24秒")
TARGET_CAR_KEYWORDS = ("22B", "IMPREZA", "MPREZA", "STI")
# When the EventLab tab bar can't be read (the events grid is still spinning on a slow
# connection), don't freeze: nudge RB toward 我的收藏 (it sits to the right) this many times,
# then wait patiently for the network. RB only moves tabs -- it can never exit or mis-buy.
EVENTLAB_TAB_UNKNOWN_MAX_NUDGES = 4
BUY_FLOW_CHILD_SCREENS = {
    "autoshow_buy_sell",
    "autoshow_showroom",
    "vehicle_buy_grid",
    "manufacturer_grid",
    "design_grid",
    "color_select",
    "car_preview",
    "purchase_confirm",
    "garage_my_cars",
    "vehicle_mastery",
    "upgrade_menu",
    "vehicle_tab",
    "post_purchase_view",
}


@dataclass
class RouteContext:
    """Mutable route facts learned while V4 navigates to EventLab pre-start."""

    favorite_filter_done: bool = False
    favorite_filter_checked: bool = False
    eventlab_card_moves: int = 0
    vehicle_card_moves: int = 0
    eventlab_tab_unknown_nudges: int = 0
    creative_focus_moves: int = 0
    locked_feature_seen: bool = False
    locked_backouts: int = 0


@dataclass(frozen=True)
class V4Decision:
    name: str
    button: str
    reason: str
    verify: str
    confidence: float = 0.0
    terminal: bool = False

    @property
    def can_press(self) -> bool:
        return bool(normalize_button(self.button))


def normalize_button(button: str) -> str:
    text = normalize_text(button)
    mapping = {
        "A": "a",
        "ENTER": "a",
        "B": "b",
        "ESC": "b",
        "X": "x",
        "Y": "y",
        "LB": "lb",
        "RB": "rb",
        "MENU": "start",
        "START": "start",
        "BACK": "back",
        "VIEW": "back",
        "BACKSPACE": "back",
        "BACKVIEW": "back",
        "DPADUP": "dpad_up",
        "DPADDOWN": "dpad_down",
        "DPADLEFT": "dpad_left",
        "DPADRIGHT": "dpad_right",
        "UP": "dpad_up",
        "DOWN": "dpad_down",
        "LEFT": "dpad_left",
        "RIGHT": "dpad_right",
    }
    if text in mapping:
        return mapping[text]
    if "/" in str(button):
        for part in str(button).split("/"):
            normalized = normalize_button(part)
            if normalized:
                return normalized
    return ""


def progress_token(v3: Any, extra: str = "") -> str:
    filter_state = getattr(v3, "filter_state", {}) or {}
    scroll_state = getattr(v3, "scroll_state", {}) or {}
    parts = [
        str(getattr(v3, "screen", "") or ""),
        str(getattr(v3, "active_tab", "") or ""),
        str(getattr(v3, "selected_item", "") or ""),
        str(filter_state.get("focused_row", "")),
        str(filter_state.get("favorite_checked", "")),
        str(scroll_state.get("position", "")),
        extra,
    ]
    return "|".join(parts)


def is_target_event(text: str) -> bool:
    normalized = normalize_text(text)
    if "SPFARM" in normalized and ("10" in normalized or "SKILLPOINT" in normalized):
        return True
    return all(keyword in normalized for keyword in ("SP", "FARM")) and any(
        keyword in normalized for keyword in TARGET_EVENT_KEYWORDS
    )


def is_22b(text: str) -> bool:
    normalized = normalize_text(text)
    return "22B" in normalized and any(keyword in normalized for keyword in TARGET_CAR_KEYWORDS)


def looks_like_eventlab(text: str) -> bool:
    normalized = normalize_text(text)
    return (
        "EVENTLAB" in normalized
        or "创建并浏览赛事" in text
        or "浏览赛事" in text
        or "游玩赛事" in text
        or "游戏赛事" in text
        or "娓哥帺璧涗簨" in text
    )


def looks_like_locked_feature_modal(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        token in normalized
        for token in (
            "功能尚未解锁",
            "尚未解锁",
            "无法使用此功能",
            "请返回地平线生活",
            "NOTAVAILABLE",
            "LOCKED",
        )
    )


def looks_like_restart_event_modal(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        token in normalized
        for token in (
            "重新开始赛事",
            "重新开始比赛",
            "确定要重新开始",
            "RESTARTEVENT",
            "RESTARTRACE",
        )
    )


def looks_like_skill_points_modal(text: str) -> bool:
    """The mastery 'not enough skill points' popup (不够购买额外加成 / 您的技术点数不足以解锁此
    额外加成). A SAFE single-『确定』dialog the buy phase leaves on screen when skill points run
    out. Mirrors buy_car_runner._is_points_exhausted_detection's tokens so the nav can DISMISS
    it (A) instead of freezing on it as a generic modal_warning. Tokens are insufficiency-
    specific (not the bare '额外加成'), so this never fires on a normal mastery purchase."""
    normalized = normalize_text(text)
    return any(
        token in normalized
        for token in (
            "不够购买额外加成",
            "技术点数不足",
            "不足以解锁此额外加成",
        )
    )


def _combined_text(v3: Any, selected_item: str = "") -> str:
    parts = [selected_item]
    for region in getattr(v3, "ocr_regions", []) or []:
        text = getattr(region, "text", "")
        if text:
            parts.append(str(text))
    return " | ".join(part for part in parts if part)


def _is_pause_tab_name(text: str) -> bool:
    normalized = normalize_text(text)
    return bool(normalized) and normalized in {normalize_text(tab) for tab in PAUSE_TABS}


def decide_mode3_navigation(v3: Any, context: RouteContext | None = None) -> V4Decision:
    """Choose the next safe navigation action toward the EventLab race menu.

    This function is deliberately conservative.  It does not press A on an
    EventLab event unless the selected title is the target farm event, and it
    does not press A in the car picker unless the selected car is 22B.
    """

    context = context or RouteContext()
    screen = str(getattr(v3, "screen", "") or "unknown")
    active_tab = str(getattr(v3, "active_tab", "") or "")
    selected_item = str(getattr(v3, "selected_item", "") or "")
    confidence = float(getattr(v3, "confidence", 0.0) or 0.0)
    filter_state = getattr(v3, "filter_state", {}) or {}

    if screen in ("race_menu", "prestart"):
        return V4Decision(
            "arrived_race_menu",
            "",
            "已经到达 EventLab 开始赛事菜单，导航阶段完成。",
            "下一步交给模式一/SmartRunner，或人工确认开始赛事按钮。",
            confidence,
            terminal=True,
        )

    if screen == "race_hud":
        return V4Decision(
            "arrived_race_hud",
            "",
            "已经识别到比赛 HUD，说明 EventLab 路线已进入比赛阶段。",
            "下一步交给 SmartRunner 维持/完成比赛；不再做菜单导航按键。",
            max(confidence, 0.82),
            terminal=True,
        )

    if screen == "controller_disconnected":
        return V4Decision(
            "dismiss_controller_modal",
            "A",
            "控制器未连接弹窗只有恢复/确认语义，先按 A 让虚拟手柄重新接入。",
            "按后必须重新识别，不再显示 controller_disconnected。",
            max(confidence, 0.75),
        )

    if screen == "skill_points_exhausted":
        return V4Decision(
            "close_skill_points_modal",
            "A",
            "买车加点阶段已到技术点数不足弹窗，按 A 关闭后才能返回暂停菜单。",
            "按后必须重新识别到 vehicle_mastery、pause_*、free_roam_hud 或其他非弹窗页面。",
            max(confidence, 0.80),
        )

    if screen == "loading_transition":
        return V4Decision(
            "wait_loading",
            "",
            "当前是过场/加载帧，没有可验证 UI。",
            "等待下一帧重新识别到明确页面后再操作。",
            confidence,
        )

    if screen == "race_pause_menu":
        return V4Decision(
            "resume_from_race_pause_menu",
            "B",
            "当前是赛事/活动中的暂停菜单，创意中心等卡片带锁；不要进入锁住的 UI，先返回当前比赛。",
            "按后必须重新识别到 race_hud、race_menu、idle_showcase 或明确的比赛/自由漫游状态；未确认不连按。",
            max(confidence, 0.74),
        )

    if screen in ("idle_showcase", "free_roam_hud"):
        return V4Decision(
            "open_pause_from_world",
            "Menu",
            "当前不在可操作菜单页，模式三需要先打开暂停菜单进入创意中心。",
            "按后必须重新识别到 pause_* 或 pause_menu；未变化则不连续盲按。",
            max(confidence, 0.58),
        )

    if screen in BUY_FLOW_CHILD_SCREENS:
        return V4Decision(
            "back_out_from_buy_flow",
            "B",
            "买车/加点阶段结束后需要逐层退回自由漫游或暂停菜单。",
            "按后必须重新识别页面变化；最多由执行器逐次验证。",
            max(confidence, 0.68),
        )

    if screen == "post_race_next":
        return V4Decision(
            "leave_post_race_next",
            "B",
            "赛后下一站页不是模式三导航目标，先返回自由漫游。",
            "按后必须重新识别到 free_roam_hud、idle_showcase 或 pause_*。",
            max(confidence, 0.76),
        )

    if screen.startswith("pause_") or screen == "pause_menu":
        return _pause_decision(screen, active_tab, selected_item, confidence, context)

    if screen == "eventlab_home":
        if context.locked_feature_seen:
            if context.locked_backouts < 2:
                return V4Decision(
                    "back_out_after_locked_feature",
                    "B",
                    "刚刚已经看到功能未解锁弹窗；先从 EventLab 首页退回上一层，避免重复进入锁定入口。",
                    "按后必须重新识别到暂停菜单/创意中心/自由漫游；若仍在 EventLab 首页则停止等待接手。",
                    max(confidence, 0.72),
                )
            return V4Decision(
                "eventlab_locked_after_retry",
                "",
                "刚刚已经看到功能未解锁弹窗；不能继续对同一个 EventLab 入口重复按 A。",
                "需要人工确认在线/地平线生活状态，或补充该锁定状态的恢复规则。",
                min(confidence, 0.62),
            )
        if active_tab and _is_pause_tab_name(active_tab) and not _same_tab(active_tab, "创意中心"):
            return V4Decision(
                "eventlab_home_pause_tab_mismatch",
                "",
                f"画面像 EventLab 入口，但 V2 顶栏仍认为当前暂停分页是 {active_tab}；先不按 A，避免进入在线/锁定功能。",
                "必须重新识别到 active_tab=创意中心，或选中项明确为 eventlab 后，才允许进入 EventLab 列表。",
                min(confidence, 0.66),
            )
        if not looks_like_eventlab(selected_item):
            creative_move = _creative_hub_focus_move(selected_item)
            if creative_move:
                button, reason = creative_move
                return V4Decision(
                    "move_creative_focus_to_eventlab",
                    button,
                    reason,
                    "按后必须重新识别到焦点变成 EventLab/创建并浏览赛事；未确认前不按 A。",
                    max(confidence, 0.64),
                )
            return V4Decision(
                "eventlab_home_focus_unknown",
                "",
                "识别到 EventLab 首页结构，但焦点文本还没有确认是 eventlab/创建并浏览赛事。",
                "重新识别或保存样本；未确认 EventLab 入口前不按 A。",
                min(confidence, 0.70),
            )
        return V4Decision(
            "enter_eventlab_events",
            "A",
            "EventLab 首页默认入口是创建并浏览赛事，进入赛事列表。",
            "按后必须重新识别到 eventlab_events、eventlab_favorites 或比赛类型弹窗。",
            max(confidence, 0.80),
        )

    if screen in ("eventlab_events", "eventlab_favorites"):
        return _eventlab_events_decision(v3, active_tab, selected_item, confidence, context)

    if screen == "eventlab_race_type":
        return V4Decision(
            "choose_single_player",
            "A",
            "比赛类型弹窗默认焦点为单人；进入车辆选择前只允许按一次 A 并验证。",
            "按后必须重新识别到 eventlab_my_cars 或 race_menu。",
            max(confidence, 0.78),
        )

    if screen == "eventlab_filter":
        return _eventlab_filter_decision(filter_state, confidence)

    if screen == "eventlab_my_cars":
        return _eventlab_my_cars_decision(selected_item, confidence, context)

    if screen in ("modal_warning", "purchase_confirm"):
        modal_text = _combined_text(v3, selected_item)
        if screen == "modal_warning" and looks_like_restart_event_modal(modal_text):
            return V4Decision(
                "confirm_restart_event",
                "A",
                "已确认是重新开始赛事确认框，模式三目标就是进入该 EventLab；默认焦点在“嗯”时按一次 A。",
                "按后必须重新识别到 race_menu、prestart、race_hud 或加载过场；没有变化不能连按。",
                max(confidence, 0.82),
            )
        if screen == "modal_warning" and looks_like_locked_feature_modal(modal_text):
            return V4Decision(
                "close_locked_feature_modal",
                "A",
                "弹窗文字是功能未解锁/当前不可用，且此类弹窗通常只有 OK；按一次 A 只关闭提示，不进入未知流程。",
                "按后必须重新识别到上一层暂停页或 EventLab 页面；如果回到同一 EventLab 入口，不能再次按 A。",
                max(confidence, 0.80),
            )
        if screen == "modal_warning" and looks_like_skill_points_modal(modal_text):
            # The buy phase leaves this popup up when skill points run out (after hours of
            # mastery spends). It can classify as generic modal_warning instead of
            # skill_points_exhausted -> here it would otherwise freeze as modal_needs_text and
            # time out. It's a safe single-『确定』dialog; press A to dismiss and keep navigating.
            return V4Decision(
                "close_skill_points_modal",
                "A",
                "弹窗是『技术点数不足/不够购买额外加成』(买车加点用尽时留下的),只有一个『确定』;按 A 关闭后继续导航。",
                "按后必须重新识别到 vehicle_mastery、pause_* 或非弹窗页面;回到同一弹窗不要连按。",
                max(confidence, 0.80),
            )
        return V4Decision(
            "modal_needs_text",
            "",
            "检测到弹窗，但 V4 还没有确认弹窗标题和当前按钮语义。",
            "必须先通过 OCR 小区域确认弹窗文字和按钮焦点，再决定 A 或 B。",
            min(confidence, 0.70),
        )

    return V4Decision(
        "wait_unknown",
        "",
        f"V4 暂时不能把当前页面 {screen} 放进模式三路线。",
        "等待或保存样本；若 120 秒无进展，执行器会进入有限恢复。",
        min(confidence, 0.55),
    )


def _creative_hub_focus_move(selected_item: str) -> tuple[str, str] | None:
    normalized = normalize_text(selected_item)
    if any(token in normalized for token in ("车库布局", "GARAGELAYOUT")):
        return (
            "DPadUp",
            "创意中心当前焦点在车库布局；EventLab 入口在它上方，先上移到 EventLab。",
        )
    if any(token in normalized for token in ("地产", "HOUSE", "PROPERTY")):
        return (
            "DPadRight",
            "创意中心当前焦点在地产；EventLab 入口在右上区域，先向右移动焦点。",
        )
    if any(token in normalized for token in ("我的创意中心", "MYCREATIVEHUB", "分享内容")):
        return (
            "DPadLeft",
            "创意中心当前焦点在右侧分享/我的创意中心；先向左移动回 EventLab 入口。",
        )
    return None


def _pause_decision(
    screen: str,
    active_tab: str,
    selected_item: str,
    confidence: float,
    context: RouteContext,
) -> V4Decision:
    if screen == "pause_creative_hub" or _same_tab(active_tab, "创意中心"):
        if context.locked_feature_seen and looks_like_eventlab(selected_item):
            return V4Decision(
                "eventlab_feature_locked",
                "",
                "EventLab 入口刚刚返回功能未解锁提示；不能在创意中心再次按 A 进入同一锁定入口。",
                "需要确认当前在线/地平线生活状态后再继续；V4 保持停止等待。",
                min(confidence, 0.62),
            )
        if looks_like_eventlab(selected_item):
            return V4Decision(
                "enter_eventlab_from_creative_hub",
                "A",
                "暂停菜单已在创意中心，且焦点是 EventLab。",
                "按后必须重新识别到 eventlab_home 或 EventLab 赛事内容。",
                max(confidence, 0.80),
            )
        if context.creative_focus_moves < 4:
            return V4Decision(
                "move_creative_focus_to_eventlab",
                "DPadLeft",
                "创意中心分页已到，但焦点还不是 EventLab；按左移动到左侧 EventLab 卡片。",
                "按后必须仍在创意中心，并且焦点/选中项更接近 EventLab。",
                max(confidence, 0.62),
            )
        return V4Decision(
            "creative_focus_not_confirmed",
            "",
            "创意中心内多次移动后仍未确认 EventLab 焦点。",
            "保存样本或人工调整焦点；不能按 A 进入未知卡片。",
            min(confidence, 0.60),
        )

    button = _tab_button(active_tab, "创意中心", PAUSE_TABS)
    if button:
        return V4Decision(
            "move_pause_tab_to_creative_hub",
            button,
            f"暂停菜单当前分页是 {active_tab or '未知'}，目标是创意中心。",
            "按后必须重新识别 active_tab；到创意中心后再检查 EventLab 焦点。",
            max(confidence, 0.64),
        )
    return V4Decision(
        "pause_tab_unknown",
        "",
        "暂停菜单分页未知，不能确定 LB/RB 方向。",
        "重新识别顶栏 active_tab 或保存样本后再移动。",
        min(confidence, 0.58),
    )


def _eventlab_events_decision(
    v3: Any,
    active_tab: str,
    selected_item: str,
    confidence: float,
    context: RouteContext,
) -> V4Decision:
    if is_target_event(selected_item):
        return V4Decision(
            "select_target_event",
            "A",
            "当前赛事卡片标题已确认是目标刷分赛事。",
            "按后必须重新识别到 eventlab_race_type、eventlab_my_cars 或 race_menu；若还在列表则不连按。",
            max(confidence, 0.82),
        )

    target_tab = "我的收藏"
    if active_tab and not _same_tab(active_tab, target_tab):
        v3_action = _first_action_button(v3, {"LB", "RB"})
        button = v3_action or _tab_button(active_tab, target_tab, EVENTLAB_TABS)
        if button:
            return V4Decision(
                "move_eventlab_tab_to_favorites",
                button,
                f"当前 EventLab 顶栏是 {active_tab}，目标赛事应优先在我的收藏；Y 只是收藏/取消当前赛事。",
                "按后必须重新识别 active_tab；到我的收藏后再检查赛事标题。",
                max(confidence, 0.70),
            )

    if not active_tab:
        # Tab bar unreadable -- almost always the events grid is still loading on a slow
        # connection. Don't freeze + fail: 我的收藏 is to the RIGHT, so nudge toward it with
        # RB (bounded), then wait patiently for the network. Once the tab becomes readable
        # again the logic above takes over and corrects the direction. RB only moves tabs.
        if context.eventlab_tab_unknown_nudges < EVENTLAB_TAB_UNKNOWN_MAX_NUDGES:
            return V4Decision(
                "nudge_eventlab_tab_to_favorites",
                "RB",
                "EventLab 顶栏暂时识别不出(多半是网络/列表仍在加载)；我的收藏在右侧，先朝它移动，再耐心等待。",
                "按后重新识别 active_tab；读到我的收藏即停止盲移。",
                min(confidence, 0.55),
            )
        return V4Decision(
            "eventlab_tab_unknown_wait",
            "",
            "EventLab 顶栏仍识别不出，已朝我的收藏移动到位；耐心等待网络/列表加载，不盲按。",
            "网络恢复后会重新识别顶栏 active_tab；或保存样本。",
            min(confidence, 0.55),
        )

    if context.eventlab_card_moves < 8:
        return V4Decision(
            "scan_favorite_event_cards",
            "DPadRight",
            "已经在目标 EventLab 分页，但当前赛事不是目标；向右扫描卡片，逐步识别标题。",
            "按后必须重新识别选中赛事标题；只有目标标题出现才允许 A。",
            max(confidence, 0.62),
        )

    return V4Decision(
        "target_event_not_found",
        "",
        "我的收藏中连续扫描仍未确认目标赛事。",
        "需要人工确认收藏列表或保存更多样本；V4 不会按 A 进入非目标赛事。",
        min(confidence, 0.60),
    )


def _eventlab_filter_decision(filter_state: dict, confidence: float) -> V4Decision:
    focused = str(filter_state.get("focused_row") or "")
    checked = filter_state.get("favorite_checked")
    if focused == "收藏" and checked is False:
        return V4Decision(
            "check_favorite_filter",
            "A",
            "筛选焦点在收藏，且复选框明确未勾选；只按一次 A 勾选。",
            "按后必须重新识别 eventlab_filter，且 收藏=已勾选，然后才能按 B。",
            max(confidence, 0.82),
        )
    if focused == "收藏" and checked is True:
        return V4Decision(
            "return_from_checked_filter",
            "B",
            "收藏已经勾选，继续按 A 会取消勾选；直接返回车辆列表。",
            "按后必须重新识别到 eventlab_my_cars，且车辆列表被收藏筛选收窄。",
            max(confidence, 0.86),
        )
    if focused and focused != "收藏":
        return V4Decision(
            "move_filter_focus_to_favorite",
            "DPadUp",
            f"筛选焦点在 {focused}，目标行是顶部收藏。",
            "按后必须重新识别到焦点=收藏；未确认前不按 A。",
            max(confidence, 0.62),
        )
    return V4Decision(
        "filter_state_unknown",
        "",
        "筛选弹窗可见，但收藏焦点或勾选状态未知。",
        "必须重新识别到 焦点=收藏 且 收藏=未勾选/已勾选 后再操作。",
        min(confidence, 0.60),
    )


def _eventlab_my_cars_decision(
    selected_item: str,
    confidence: float,
    context: RouteContext,
) -> V4Decision:
    if not context.favorite_filter_done:
        return V4Decision(
            "open_vehicle_favorite_filter",
            "Y",
            "进入 EventLab 车辆列表后，先打开筛选并确认收藏过滤；即使当前焦点看起来是 22B，也先验证筛选状态。",
            "按后必须重新识别到 eventlab_filter；在筛选里根据勾选状态决定 A 或 B。",
            max(confidence, 0.72),
        )

    if is_22b(selected_item):
        return V4Decision(
            "select_22b_for_eventlab",
            "A",
            "收藏筛选已确认，且 EventLab 车辆列表中选中的车已确认是 Impreza 22B-STI。",
            "按后必须重新识别到 race_menu；如果仍在车辆列表，必须重新确认 22B 再补按。",
            max(confidence, 0.84),
        )

    if context.vehicle_card_moves < 10:
        return V4Decision(
            "scan_filtered_vehicle_cards",
            "DPadRight",
            "收藏筛选已处理，但当前车还不是 22B；逐格扫描车辆卡片。",
            "按后必须重新识别选中车辆；只有 22B 成为焦点才允许 A。",
            max(confidence, 0.62),
        )

    return V4Decision(
        "target_vehicle_not_found",
        "",
        "收藏筛选后仍未找到 22B。",
        "需要人工确认收藏状态、车辆列表或样本；V4 不会选择非 22B 车辆。",
        min(confidence, 0.60),
    )


def _same_tab(active: str, target: str) -> bool:
    return bool(active) and normalize_text(active) == normalize_text(target)


def _tab_button(active: str, target: str, order) -> str:
    active_norm = normalize_text(active)
    target_norm = normalize_text(target)
    if not active_norm or active_norm == target_norm:
        return ""
    normalized_order = [normalize_text(item) for item in order]
    try:
        current = normalized_order.index(active_norm)
        desired = normalized_order.index(target_norm)
    except ValueError:
        return ""
    return "RB" if desired > current else "LB"


def _first_action_button(v3: Any, allowed: set[str]) -> str:
    for action in getattr(v3, "actions", []) or []:
        button = str(getattr(action, "button", "") or "")
        if normalize_text(button) in {normalize_text(item) for item in allowed}:
            return button
    return ""


# --- Farm loop: vision-guided replacement for the V1 SmartRunner state machine ---

FARM_START_FOCUS_KEYWORDS = ("开始赛事", "开始竞赛", "开始比赛", "STARTEVENT", "STARTRACE")


def _is_start_race_focus(selected_item: str) -> bool:
    text = str(selected_item or "")
    normalized = normalize_text(text)
    if any(normalize_text(keyword) in normalized for keyword in FARM_START_FOCUS_KEYWORDS):
        return True
    return "开始" in text and any(token in text for token in ("赛事", "竞赛", "比赛"))


def decide_farm_loop(v3: Any, graceful_exit: bool = False) -> V4Decision:
    """Choose the next farm-loop action from V3 hybrid recognition only.

    Ports the V1 SmartRunner state machine (prestart->A, racing->throttle,
    results->X / graceful A, confirm-restart->A, post-race->B, pause->B,
    controller-disconnected->A) onto the aspect-robust V3 hybrid screens, so the
    farm phase no longer depends on V1's fixed-fraction ForzaScreenDetector.

    The runner interprets ``race_drive_throttle`` (button "") as "hold full
    throttle this cycle" rather than a button tap.
    """
    screen = str(getattr(v3, "screen", "") or "unknown")
    selected_item = str(getattr(v3, "selected_item", "") or "")
    confidence = float(getattr(v3, "confidence", 0.0) or 0.0)

    if screen == "controller_disconnected":
        return V4Decision(
            "farm_dismiss_controller",
            "A",
            "控制器未连接弹窗,按 A 让虚拟手柄重新接入。",
            "按后必须重新识别,不再显示 controller_disconnected。",
            max(confidence, 0.75),
        )

    if screen == "race_hud":
        return V4Decision(
            "race_drive_throttle",
            "",
            "比赛进行中,保持油门到底。",
            "保持识别 race_hud;变为 race_result/race_menu 时切换动作。",
            max(confidence, 0.80),
        )

    # EventLab race start menu: trust the focused tile text. This menu reads as
    # race_menu, but is sometimes misclassified as pause_story (the inverse of
    # the race_hud<->race_menu confusion). In either case a focused
    # 开始赛事/开始竞赛赛事 tile means "start the race" -> press A.
    if _is_start_race_focus(selected_item) and (
        screen in ("race_menu", "prestart")
        or screen.startswith("pause_")
        or screen == "pause_menu"
    ):
        return V4Decision(
            "farm_start_race",
            "A",
            f"开始赛事菜单(焦点=开始赛事,画面识别为 {screen}),按 A 开赛。",
            "按后应进入 race_hud 或 loading_transition;否则重新校准焦点。",
            max(confidence, 0.80),
        )

    if screen in ("race_menu", "prestart"):
        # Do NOT press DpadUp to "calibrate" here: in-race DpadUp opens Photo
        # Mode, and a race_menu-without-start-focus frame is usually a misread
        # countdown/driving frame rather than a genuine wrong cursor. Wait for a
        # confirmed 开始赛事 focus instead; the runner holds throttle through the
        # launch window so a real race still launches.
        return V4Decision(
            "farm_wait_race_menu_focus",
            "",
            f"识别为开始赛事菜单但未确认焦点=开始赛事(当前 {selected_item or '空'});不按 DpadUp(赛中=拍照模式),等待重新识别。",
            "等待焦点变成开始赛事再按 A;若其实是比赛/过场帧,执行器会按在比赛中保持油门处理。",
            min(confidence, 0.62),
        )

    if screen == "race_result":
        if graceful_exit:
            return V4Decision(
                "farm_graceful_exit_results",
                "A",
                "结算页且已请求平滑退出,按 A 退出比赛把控制权交还上层。",
                "按后应进入 post_race_next / pause_* / free_roam_hud。",
                max(confidence, 0.80),
            )
        return V4Decision(
            "farm_restart_results",
            "X",
            "结算页,按 X 重开下一圈继续刷分。",
            "按后应进入重开确认框或直接 loading/race_hud。",
            max(confidence, 0.80),
        )

    if screen in ("modal_warning", "confirm_restart"):
        modal_text = _combined_text(v3, selected_item)
        is_restart = looks_like_restart_event_modal(modal_text)
        if graceful_exit:
            # Leaving the farm: cancel any popup with B instead of confirming
            # into a fresh race; the next race_result frame exits with A.
            return V4Decision(
                "farm_cancel_restart",
                "B",
                "平滑退出中,遇到弹窗按 B 取消,不确认进入新比赛。",
                "按后应回到结算页或比赛。",
                max(confidence, 0.74),
            )
        # In the farm loop a popup is almost always a start/restart/confirm gate
        # (重新开始赛事 / 确认开始 / 车辆或赛事提示). Press A to proceed into the
        # race rather than waiting forever. Previously ONLY the explicit
        # 重新开始赛事 modal was handled, so any other popup at the start fell
        # through to farm_wait_unknown and the runner just waited -- the race
        # never auto-started ("买完车后不会自动刷图"). Verify-after-press keeps it
        # safe: if the popup persists the next frame re-decides, and the
        # mode-three farm watchdog stops a genuinely stuck modal.
        return V4Decision(
            "farm_confirm_restart" if is_restart else "farm_confirm_modal",
            "A",
            (
                "重开确认框,按 A 确认重新开始赛事。"
                if is_restart
                else f"刷分中遇到弹窗(焦点/文本={selected_item or modal_text or '空'}),按 A 确认进入比赛。"
            ),
            "按后应进入 loading_transition 或 race_hud;若弹窗仍在,下一帧重新识别再决定。",
            max(confidence, 0.80 if is_restart else 0.74),
        )

    if screen == "post_race_next":
        return V4Decision(
            "farm_leave_post_race",
            "B",
            "赛后下一站页,按 B 返回自由漫游;平滑退出时此处即可交还上层。",
            "按后应进入 free_roam_hud / idle_showcase / pause_*。",
            max(confidence, 0.76),
            terminal=graceful_exit,
        )

    if screen == "race_pause_menu":
        return V4Decision(
            "farm_resume_from_race_pause",
            "B",
            "比赛中的暂停菜单(创意中心等带锁),按 B 返回当前比赛。",
            "按后应重新识别到 race_hud / race_menu。",
            max(confidence, 0.74),
        )

    if screen.startswith("pause_") or screen == "pause_menu":
        return V4Decision(
            "farm_return_from_pause",
            "B",
            "暂停菜单,按 B 返回赛事/比赛页面后重新识别。",
            "按后应进入 race_menu / race_hud;未变化不连按。",
            max(confidence, 0.64),
        )

    if screen == "loading_transition":
        return V4Decision(
            "farm_wait_loading",
            "",
            "过场/加载帧,没有可操作 UI,等待下一帧。",
            "等待重新识别到明确页面。",
            confidence,
        )

    return V4Decision(
        "farm_wait_unknown",
        "",
        f"刷分阶段暂时不能识别页面 {screen};等待重新识别。",
        "等待;若刚才在比赛中,执行器会保持油门避免赛中松油。",
        min(confidence, 0.55),
    )


# --- Buy phase: vision-guided replacement for the V1 BuyCarRunner state machine ---

SUBARU_KEYWORDS = ("斯巴鲁", "SUBARU")


def looks_like_subaru(text: str) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(keyword) in normalized for keyword in SUBARU_KEYWORDS)


@dataclass
class BuyContext:
    """Mutable facts learned while the vision buy phase runs.

    ``purchase_armed`` is the key safety latch: the purchase-confirm/preview/
    color/design steps only press A when 22B has been positively selected in the
    grid, mirroring the V1 BuyCarRunner's "never buy an unconfirmed car" rule.
    """

    purchase_armed: bool = False
    vehicle_scan_moves: int = 0
    manufacturer_scan_moves: int = 0
    pause_cars_moves: int = 0
    mastery_runs: int = 0


def decide_buy_loop(v3: Any, context: BuyContext | None = None) -> V4Decision:
    """Choose the next buy/skill-point action from V3 hybrid recognition.

    Mirrors the V1 BuyCarRunner flow (pause -> 车辆 -> 购买新车与二手车 -> 车展 ->
    制造商/斯巴鲁 -> 22B -> 设计/颜色/预览 -> 购买确认 -> 加点 -> 技术点数用完) but
    drives off the aspect-robust V3 screen + selected_item instead of fixed-
    fraction OCR grid coordinates. Grid scanning and the fixed mastery sequence
    are executed by the runner (they are stateful multi-step actions); this pure
    function only emits the next single decision and the safety gates.
    """
    context = context or BuyContext()
    screen = str(getattr(v3, "screen", "") or "unknown")
    selected = str(getattr(v3, "selected_item", "") or "")
    confidence = float(getattr(v3, "confidence", 0.0) or 0.0)

    if screen == "skill_points_exhausted":
        return V4Decision(
            "buy_phase_done",
            "",
            "技术点数不足弹窗 = 买车加点阶段完成,交还上层去 EventLab 导航。",
            "上层据此进入 EventLab 路线;不再在买车流程按键。",
            max(confidence, 0.82),
            terminal=True,
        )

    if screen == "controller_disconnected":
        return V4Decision(
            "buy_dismiss_controller",
            "A",
            "控制器未连接弹窗,按 A 让虚拟手柄重新接入。",
            "按后必须重新识别,不再显示 controller_disconnected。",
            max(confidence, 0.75),
        )

    # Purchase confirm: ONLY buy when 22B has been positively selected.
    if screen == "purchase_confirm":
        if context.purchase_armed:
            return V4Decision(
                "buy_confirm_purchase",
                "A",
                "购买确认弹窗,且已确认走的是 22B 路径,按 A 购买。",
                "按后应进入新车展示页或车辆页。",
                max(confidence, 0.82),
            )
        return V4Decision(
            "buy_cancel_unconfirmed_purchase",
            "B",
            "购买确认弹窗,但还没确认选中 22B;按 B 取消,绝不误买。",
            "按后回到选车/车展页,确认 22B 后再走购买。",
            max(confidence, 0.80),
        )

    if screen == "vehicle_buy_grid":
        if is_22b(selected):
            return V4Decision(
                "buy_select_22b",
                "A",
                "购买车辆网格中 22B 已是焦点,按 A 选择(并锁定购买路径)。",
                "按后应进入设计/颜色/预览或购买确认。",
                max(confidence, 0.84),
            )
        return V4Decision(
            "buy_scan_vehicle_grid",
            "DPadRight",
            f"购买网格当前是 {selected or '未知'},不是 22B;右移逐格扫描。",
            "按后必须重新识别选中车辆;只有 22B 成为焦点才允许 A。",
            max(confidence, 0.62),
        )

    if screen == "manufacturer_grid":
        if looks_like_subaru(selected):
            return V4Decision(
                "buy_enter_subaru",
                "A",
                "制造商列表已在斯巴鲁,按 A 进入斯巴鲁车展。",
                "按后应进入车辆网格(斯巴鲁车系)。",
                max(confidence, 0.80),
            )
        return V4Decision(
            "buy_scan_manufacturer",
            "DPadDown",
            f"制造商列表当前是 {selected or '未知'},向下找斯巴鲁。",
            "按后必须重新识别;到斯巴鲁再 A。",
            max(confidence, 0.60),
        )

    if screen == "design_grid":
        if context.purchase_armed:
            return V4Decision(
                "buy_design_to_color",
                "Y",
                "推荐设计页,按 Y 进入出厂颜色。",
                "按后应进入 color_select。",
                max(confidence, 0.72),
            )
        return V4Decision(
            "buy_back_unconfirmed_design",
            "B",
            "推荐设计页但未确认 22B 路径,按 B 返回,避免误买。",
            "按后回到选车页确认 22B。",
            max(confidence, 0.74),
        )

    if screen == "color_select":
        if context.purchase_armed:
            return V4Decision(
                "buy_color_confirm",
                "A",
                "出厂颜色页,按 A 确认默认颜色。",
                "按后应进入 car_preview 或购买确认。",
                max(confidence, 0.72),
            )
        return V4Decision(
            "buy_back_unconfirmed_color",
            "B",
            "出厂颜色页但未确认 22B 路径,按 B 返回,避免误买。",
            "按后回到选车页确认 22B。",
            max(confidence, 0.74),
        )

    if screen == "car_preview":
        if context.purchase_armed:
            return V4Decision(
                "buy_preview_advance",
                "A",
                "车辆预览页,按 A 进入购买确认。",
                "按后应进入 purchase_confirm。",
                max(confidence, 0.72),
            )
        return V4Decision(
            "buy_back_unconfirmed_preview",
            "B",
            "车辆预览页但未确认选中 22B,按 B 返回,绝不购买当前车辆。",
            "按后回到选车页确认 22B。",
            max(confidence, 0.80),
        )

    if screen in ("autoshow_buy_sell", "autoshow_showroom"):
        return V4Decision(
            "buy_enter_showroom",
            "A",
            "购买与出售/车展页,按 A 进入车展网格。",
            "按后应进入 vehicle_buy_grid 或 manufacturer_grid。",
            max(confidence, 0.68),
        )

    if screen == "pause_vehicle_entry":
        if "购买" in selected or "二手车" in selected:
            return V4Decision(
                "buy_enter_purchase_menu",
                "A",
                "车辆页焦点在购买新车与二手车,按 A 进入。",
                "按后应进入购买与出售/车展页。",
                max(confidence, 0.78),
            )
        return V4Decision(
            "buy_move_to_purchase_menu",
            "DPadLeft",
            f"车辆页当前焦点是 {selected or '未知'},左移找购买新车与二手车。",
            "按后必须重新识别焦点;焦点=购买新车与二手车再 A。",
            max(confidence, 0.60),
        )

    if screen == "vehicle_mastery":
        return V4Decision(
            "buy_spend_mastery",
            "",
            "车辆熟练度页:由执行器跑固定加点序列,直到技术点数不足。",
            "执行器跑完序列后必须重新识别;出现技术点数不足弹窗 = 完成。",
            max(confidence, 0.70),
        )

    if screen == "post_purchase_view":
        return V4Decision(
            "buy_leave_post_purchase",
            "B",
            "新车展示页,按 B 返回去加点/继续。",
            "按后应进入车辆页或购买与出售页。",
            max(confidence, 0.72),
        )

    if screen.startswith("pause_") or screen == "pause_menu":
        return V4Decision(
            "buy_pause_to_vehicle",
            "RB",
            "暂停菜单,按 RB 切到车辆页准备买车。",
            "按后应进入 pause_vehicle_entry。",
            max(confidence, 0.62),
        )

    if screen == "loading_transition":
        return V4Decision(
            "buy_wait_loading",
            "",
            "过场/加载帧,等待下一帧。",
            "等待重新识别到明确页面。",
            confidence,
        )

    return V4Decision(
        "buy_wait_unknown",
        "",
        f"买车阶段暂时不能识别页面 {screen};等待重新识别。",
        "等待;不确定时不按键,避免误买。",
        min(confidence, 0.55),
    )
