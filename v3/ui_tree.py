from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ChildRoute:
    trigger: str
    target: str
    button: str = "A"
    verify: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UINode:
    node_id: str
    title: str
    screen: str
    parent: str = ""
    tab_scope: str = ""
    tabs: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    children: tuple[ChildRoute, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class UIStateDescription:
    node_id: str = ""
    title: str = ""
    path: tuple[str, ...] = ()
    tab_scope: str = ""
    active_tab: str = ""
    tabs: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    children: tuple[ChildRoute, ...] = ()

    @property
    def path_text(self) -> str:
        return " > ".join(self.path)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "path": list(self.path),
            "tab_scope": self.tab_scope,
            "active_tab": self.active_tab,
            "tabs": list(self.tabs),
            "options": list(self.options),
            "children": [child.to_dict() for child in self.children],
        }


PAUSE_TABS = ("剧情", "车辆", "我的地平线", "在线", "创意中心", "商店")
AUTOSHOW_TABS = ("剧情", "购买与出售", "车辆", "角色")
EVENTLAB_TABS = ("精选", "热门", "本月最佳", "最新最热", "全新", "最爱的创作者", "我的收藏", "我的历史记录")


UI_NODES: dict[str, UINode] = {
    "free_roam_hud": UINode(
        "free_roam_hud",
        "自由漫游 HUD",
        "free_roam_hud",
        options=("打开暂停菜单", "驾驶/比赛入口", "地图事件"),
        children=(ChildRoute("Menu", "pause_story", "Menu", "重新识别到 pause_* 顶层分页"),),
    ),
    "idle_showcase": UINode(
        "idle_showcase",
        "车辆展示/待机页",
        "idle_showcase",
        options=("唤醒 UI", "返回上一层", "打开暂停菜单"),
        children=(
            ChildRoute("A", "context_after_wake", "A", "出现可识别菜单、弹窗或 HUD"),
            ChildRoute("B", "context_after_back", "B", "出现上一层菜单或 HUD"),
            ChildRoute("Menu", "pause_story", "Menu", "出现 pause_* 顶层分页"),
        ),
    ),
    "loading_transition": UINode(
        "loading_transition",
        "Loading/black transition",
        "loading_transition",
        options=("wait", "re-detect next frame"),
        notes="No actionable UI is visible; do not press buttons from this state.",
    ),
    "race_pause_menu": UINode(
        "race_pause_menu",
        "赛事/活动中暂停菜单",
        "race_pause_menu",
        tab_scope="赛事暂停顶部分页",
        tabs=PAUSE_TABS,
        options=("返回当前比赛", "切到剧情页查看返回/退出比赛", "不要进入带锁功能"),
        children=(
            ChildRoute("返回当前比赛", "race_hud", "B", "回到比赛 HUD 或开始赛事菜单"),
            ChildRoute("剧情页", "race_pause_story", "LB/RB", "看到返回比赛/退出比赛等赛事按钮"),
        ),
        notes="Pause menu opened while an EventLab/race is active; locked tiles mean normal menu routing is unsafe.",
    ),
    "pause_root": UINode(
        "pause_root",
        "暂停菜单",
        "pause_menu",
        tab_scope="暂停菜单顶部分页",
        tabs=PAUSE_TABS,
    ),
    "pause_story": UINode(
        "pause_story",
        "暂停菜单 / 剧情",
        "pause_story",
        parent="pause_root",
        tab_scope="暂停菜单顶部分页",
        tabs=PAUSE_TABS,
        options=("Festival Playlist / 欢迎来到日本", "世界地图", "收集簿", "下一站", "设置", "退出游戏"),
        children=(
            ChildRoute("世界地图", "world_map", "A", "出现地图控制提示"),
            ChildRoute("下一站", "post_race_next", "A", "出现下一站推荐页或活动卡"),
            ChildRoute("设置", "settings_menu", "A", "出现设置分类"),
        ),
    ),
    "pause_vehicle_entry": UINode(
        "pause_vehicle_entry",
        "暂停菜单 / 车辆",
        "pause_vehicle_entry",
        parent="pause_root",
        tab_scope="暂停菜单顶部分页",
        tabs=PAUSE_TABS,
        options=("购买新车与二手车", "更换车辆", "车辆熟练度", "车辆专精", "升级和改装车", "调校车辆", "秘藏座驾", "车房宝物", "礼物掉落箱", "汽车喇叭"),
        children=(
            ChildRoute("购买新车与二手车", "autoshow_buy_sell", "A", "出现购买与出售标题和车展/拍卖场菜单"),
            ChildRoute("更换车辆", "garage_my_cars", "A", "出现我的车辆/车辆列表"),
            ChildRoute("车辆熟练度", "vehicle_mastery", "A", "出现技能树节点"),
            ChildRoute("调校车辆", "tuning_menu", "A", "出现调校页面"),
        ),
    ),
    "autoshow_buy_sell": UINode(
        "autoshow_buy_sell",
        "购买与出售",
        "autoshow_buy_sell",
        parent="pause_vehicle_entry",
        tab_scope="购买与出售顶部分页",
        tabs=AUTOSHOW_TABS,
        options=("车展", "拍卖场", "车辆通行证", "车辆包", "票券车辆"),
        children=(
            ChildRoute("车展", "autoshow_showroom", "A", "出现厂商/车辆购买列表"),
            ChildRoute("拍卖场", "auction_house", "A", "出现拍卖搜索/列表"),
            ChildRoute("车辆通行证", "car_pass", "A", "出现车辆通行证页面"),
            ChildRoute("车辆包", "car_packs", "A", "出现车辆包页面"),
            ChildRoute("票券车辆", "voucher_cars", "A", "出现票券车辆页面"),
        ),
        notes="这里的“剧情/车辆/角色”不是暂停菜单顶层分页，而是购买与出售子页面的 tab。",
    ),
    "autoshow_showroom": UINode(
        "autoshow_showroom",
        "购买与出售 / 车展",
        "autoshow_showroom",
        parent="autoshow_buy_sell",
        tab_scope="购买车辆制造商分页",
        options=("制造商分页", "车辆卡片", "排序", "筛选", "前往制造商"),
        children=(ChildRoute("车辆卡片", "vehicle_buy_grid", "A", "出现购买确认或车辆详情"),),
    ),
    "vehicle_buy_grid": UINode(
        "vehicle_buy_grid",
        "购买车辆网格",
        "vehicle_buy_grid",
        parent="autoshow_showroom",
        tab_scope="购买车辆制造商分页",
        options=("车辆卡片", "排序", "筛选", "购买车展车辆票券", "前往制造商", "切换详情", "切换数据"),
        children=(
            ChildRoute("前往制造商", "manufacturer_grid", "Back/View", "出现制造商表格和右侧滚动条"),
            ChildRoute("筛选", "eventlab_filter", "Y", "出现筛选字段"),
            ChildRoute("目标车辆", "modal_warning", "A", "出现购买/确认/限制检查弹窗"),
        ),
    ),
    "manufacturer_grid": UINode(
        "manufacturer_grid",
        "制造商选择列表",
        "manufacturer_grid",
        parent="vehicle_buy_grid",
        options=("制造商表格", "当前焦点品牌", "右侧滚动条", "选择", "取消"),
        children=(ChildRoute("品牌", "vehicle_buy_grid", "A", "返回购买车辆网格并切到该品牌分页"),),
    ),
    "design_grid": UINode(
        "design_grid",
        "推荐设计",
        "design_grid",
        parent="vehicle_buy_grid",
        options=("出厂颜色", "推荐设计卡片", "颜色", "搜寻", "返回"),
        children=(
            ChildRoute("出厂颜色/设计卡片", "car_preview", "A/Enter", "进入车辆预览页"),
            ChildRoute("颜色", "color_select", "Y", "切换到颜色/出厂颜色选择"),
        ),
    ),
    "color_select": UINode(
        "color_select",
        "出厂颜色选择",
        "color_select",
        parent="design_grid",
        options=("颜色分类", "当前颜色", "确定", "返回"),
        children=(ChildRoute("确定", "car_preview", "A/Enter", "进入车辆预览页"),),
    ),
    "car_preview": UINode(
        "car_preview",
        "车辆购买预览",
        "car_preview",
        parent="design_grid",
        options=("车辆预览", "价格", "选择", "返回", "更改视角"),
        children=(ChildRoute("选择", "purchase_confirm", "A/Enter", "出现购买车辆确认弹窗"),),
    ),
    "purchase_confirm": UINode(
        "purchase_confirm",
        "购买车辆确认",
        "purchase_confirm",
        parent="car_preview",
        options=("购买", "购买车展车辆票券", "取消", "价格"),
        children=(ChildRoute("购买", "post_purchase_view", "A/Enter", "进入购买后展示/加载转场"),),
    ),
    "garage_my_cars": UINode(
        "garage_my_cars",
        "车库 / 我的车辆",
        "garage_my_cars",
        parent="pause_vehicle_entry",
        options=("车辆卡片", "筛选", "排序", "切换详情", "前往制造商"),
        children=(ChildRoute("车辆卡片", "modal_warning", "A", "可能出现上车/收藏/查看车辆操作弹窗"),),
    ),
    "vehicle_mastery": UINode(
        "vehicle_mastery",
        "车辆熟练度技能树",
        "vehicle_mastery",
        parent="pause_vehicle_entry",
        options=("技能节点", "XP 节点", "抽奖/奖励节点"),
    ),
    "upgrade_menu": UINode(
        "upgrade_menu",
        "升级和调校子菜单",
        "upgrade_menu",
        parent="pause_vehicle_entry",
        options=("自定义升级", "自动升级", "升级预设", "自定义调校", "我的调校设置", "寻找调校设置", "车辆熟练度", "车辆专精"),
        children=(ChildRoute("返回车辆分页", "pause_vehicle_entry", "B/Esc", "回到暂停菜单 / 车辆"),),
    ),
    "pause_my_horizon": UINode(
        "pause_my_horizon",
        "暂停菜单 / 我的地平线",
        "pause_my_horizon",
        parent="pause_root",
        tab_scope="暂停菜单顶部分页",
        tabs=PAUSE_TABS,
        options=("我的地产", "快速移动至住所", "信息中心", "抽奖", "超级抽奖", "奖章", "无人机模式"),
        children=(
            ChildRoute("快速移动至住所", "modal_warning", "A", "出现是否快速移动确认弹窗"),
            ChildRoute("我的地产", "player_house", "A", "出现地产/住所页面"),
        ),
    ),
    "pause_online": UINode(
        "pause_online",
        "暂停菜单 / 在线",
        "pause_online",
        parent="pause_root",
        tab_scope="暂停菜单顶部分页",
        tabs=PAUSE_TABS,
        options=("Horizon Play", "在线好友", "在线玩家列表", "车队", "劲敌", "极限竞速 LINK"),
        children=(
            ChildRoute("在线好友", "online_player_list", "A", "出现好友/玩家列表"),
            ChildRoute("车队", "convoy_menu", "A", "出现车队页面"),
        ),
    ),
    "pause_creative_hub": UINode(
        "pause_creative_hub",
        "暂停菜单 / 创意中心",
        "pause_creative_hub",
        parent="pause_root",
        tab_scope="暂停菜单顶部分页",
        tabs=PAUSE_TABS,
        options=("eventlab", "车库布局", "地产", "涂装设计", "我的创意中心", "彩绘纹饰分组", "调校", "照片模式", "照片图库", "道具预制件"),
        children=(
            ChildRoute("eventlab", "eventlab_home", "A", "出现 EventLab 赛事/分页"),
            ChildRoute("车库布局", "eventlab_garage_layout", "A", "出现车库布局内容"),
            ChildRoute("我的创意中心", "eventlab_creator_hub", "A", "出现分享内容"),
        ),
    ),
    "pause_store": UINode(
        "pause_store",
        "暂停菜单 / 商店",
        "pause_store",
        parent="pause_root",
        tab_scope="暂停菜单顶部分页",
        tabs=PAUSE_TABS,
        options=("高级版升级捆绑包", "车辆通行证", "车辆包", "车展", "拍卖场", "票券车辆"),
        children=(
            ChildRoute("车展", "autoshow_buy_sell", "A", "出现购买与出售页面"),
            ChildRoute("拍卖场", "autoshow_buy_sell", "A", "出现购买与出售页面"),
        ),
    ),
    "eventlab_home": UINode(
        "eventlab_home",
        "EventLab 首页",
        "eventlab_home",
        parent="pause_creative_hub",
        options=("创建并浏览赛事", "赛事列表", "我的创意中心"),
        children=(ChildRoute("创建并浏览赛事", "eventlab_events", "A", "出现 EventLab 赛事 tab 条"),),
    ),
    "eventlab_events": UINode(
        "eventlab_events",
        "EventLab 赛事列表",
        "eventlab_events",
        parent="eventlab_home",
        tab_scope="EventLab 赛事分页",
        tabs=EVENTLAB_TABS,
        options=("赛事卡片", "赛事选项", "创建者信息", "切换最爱", "搜索", "筛选"),
        children=(
            ChildRoute("赛事卡片", "eventlab_race_type", "A", "出现选择比赛类型弹窗"),
            ChildRoute("筛选", "eventlab_filter", "Y", "出现筛选字段"),
            ChildRoute("切换最爱", "eventlab_events", "Y", "只改变当前赛事收藏状态；看到“移除最爱”不代表进入收藏列表"),
        ),
    ),
    "eventlab_favorites": UINode(
        "eventlab_favorites",
        "EventLab / 我的收藏",
        "eventlab_favorites",
        parent="eventlab_events",
        tab_scope="EventLab 赛事分页",
        tabs=EVENTLAB_TABS,
        options=("收藏赛事卡片", "赛事选项", "查看赛事信息", "移除最爱"),
        children=(ChildRoute("收藏赛事卡片", "eventlab_race_type", "A", "出现选择比赛类型弹窗"),),
        notes="只有 OCR 明确看到“我的收藏”分页/列表时才使用此节点；底部“移除最爱”只是当前赛事收藏状态。",
    ),
    "eventlab_race_type": UINode(
        "eventlab_race_type",
        "EventLab / 选择比赛类型",
        "eventlab_race_type",
        parent="eventlab_events",
        options=("单人", "合作", "玩家对战"),
        children=(ChildRoute("单人", "eventlab_my_cars", "A", "出现我的车辆选择页"),),
    ),
    "eventlab_my_cars": UINode(
        "eventlab_my_cars",
        "EventLab / 我的车辆",
        "eventlab_my_cars",
        parent="eventlab_race_type",
        options=("车辆卡片", "筛选", "排序", "前往制造商", "切换详情", "切换数据"),
        children=(
            ChildRoute("筛选", "eventlab_filter", "Y", "出现收藏/性能等级/车辆类型筛选"),
            ChildRoute("前往制造商", "manufacturer_grid", "Back/View", "出现制造商表格和右侧滚动条"),
            ChildRoute("22B", "race_menu", "A", "出现比赛开始菜单或车辆限制检查"),
        ),
    ),
    "eventlab_filter": UINode(
        "eventlab_filter",
        "EventLab / 筛选",
        "eventlab_filter",
        parent="eventlab_my_cars",
        options=("收藏", "性能等级", "车辆类型", "制造商", "国家/地区"),
    ),
    "race_menu": UINode(
        "race_menu",
        "比赛开始菜单",
        "race_menu",
        parent="eventlab_my_cars",
        options=("开始赛事", "赛事选项", "难度", "车辆", "蓝图"),
        children=(ChildRoute("开始赛事", "race_hud", "A", "进入比赛 HUD"),),
    ),
    "race_hud": UINode(
        "race_hud",
        "比赛 HUD",
        "race_hud",
        parent="race_menu",
        options=("比赛进度", "速度", "时间", "安娜/LINK"),
        children=(ChildRoute("完赛", "race_result", "", "出现结算/奖励页"),),
    ),
    "race_result": UINode(
        "race_result",
        "比赛结算页",
        "race_result",
        parent="race_hud",
        options=("继续", "重开", "奖励", "车手", "时间/积分"),
        children=(
            ChildRoute("继续", "post_race_next", "A", "出现赛后下一站或自由漫游"),
            ChildRoute("重开", "race_menu", "X/A", "回到比赛开始/确认流程"),
        ),
    ),
    "post_race_next": UINode(
        "post_race_next",
        "赛后下一站",
        "post_race_next",
        parent="race_result",
        options=("下一站推荐", "活动卡", "返回自由漫游"),
        children=(ChildRoute("返回", "free_roam_hud", "B", "回到自由漫游 HUD"),),
    ),
    "modal_warning": UINode(
        "modal_warning",
        "弹窗/确认框",
        "modal_warning",
        options=("标题文字", "当前按钮焦点", "嗯/不", "是/否", "确定/取消"),
        notes="弹窗标题和按钮焦点必须分开：标题说明意图，按钮焦点说明 A 会选择什么。",
    ),
    "skill_points_exhausted": UINode(
        "skill_points_exhausted",
        "技术点数不足弹窗",
        "skill_points_exhausted",
        parent="vehicle_mastery",
        options=("不够购买额外加成", "确定"),
        children=(ChildRoute("确定", "vehicle_mastery", "A", "关闭弹窗后回到车辆熟练度技能树"),),
    ),
    "world_map": UINode("world_map", "世界地图", "world_map", parent="pause_story", options=("筛选", "设定路线", "关闭地图")),
    "settings_menu": UINode("settings_menu", "设置菜单", "settings_menu", parent="pause_story", options=("难度", "控制", "视频", "辅助功能")),
    "tuning_menu": UINode("tuning_menu", "调校菜单", "tuning_menu", parent="pause_vehicle_entry", options=("轮胎", "齿轮", "防倾杆", "空气动力学", "差速器")),
    "online_player_list": UINode("online_player_list", "在线玩家列表", "online_player_list", parent="pause_online", options=("好友", "最近玩家", "邀请玩家加入车队")),
    "external_overlay": UINode("external_overlay", "外部覆盖层", "external_overlay", options=("Steam/系统覆盖层", "返回游戏")),
    "notification_overlay": UINode("notification_overlay", "系统通知覆盖层", "notification_overlay", options=("季节通知", "等待/唤醒")),
}


SCREEN_TO_NODE = {
    "pause_menu": "pause_root",
    "pause_story": "pause_story",
    "pause_vehicle": "pause_vehicle_entry",
    "pause_vehicle_entry": "pause_vehicle_entry",
    "autoshow_buy_sell": "autoshow_buy_sell",
    "autoshow_showroom": "autoshow_showroom",
    "vehicle_buy_grid": "vehicle_buy_grid",
    "manufacturer_grid": "manufacturer_grid",
    "design_grid": "design_grid",
    "color_select": "color_select",
    "car_preview": "car_preview",
    "purchase_confirm": "purchase_confirm",
    "vehicle_mastery": "vehicle_mastery",
    "pause_my_horizon": "pause_my_horizon",
    "pause_online": "pause_online",
    "pause_creative_hub": "pause_creative_hub",
    "pause_store": "pause_store",
    "eventlab_home": "eventlab_home",
    "eventlab_events": "eventlab_events",
    "eventlab_favorites": "eventlab_favorites",
    "eventlab_race_type": "eventlab_race_type",
    "eventlab_filter": "eventlab_filter",
    "eventlab_my_cars": "eventlab_my_cars",
    "race_menu": "race_menu",
    "race_hud": "race_hud",
    "race_result": "race_result",
    "post_race_next": "post_race_next",
    "controller_disconnected": "modal_warning",
    "skill_points_exhausted": "skill_points_exhausted",
    "upgrade_menu": "upgrade_menu",
    "modal_warning": "modal_warning",
    "world_map": "world_map",
    "settings_menu": "settings_menu",
    "tuning_menu": "tuning_menu",
    "online_player_list": "online_player_list",
    "free_roam_hud": "free_roam_hud",
    "idle_showcase": "idle_showcase",
    "loading_transition": "loading_transition",
    "race_pause_menu": "race_pause_menu",
    "external_overlay": "external_overlay",
    "notification_overlay": "notification_overlay",
}


def describe_ui_state(screen: str, active_tab: str = "", selected_item: str = "") -> UIStateDescription:
    node_id = SCREEN_TO_NODE.get(screen, "")
    if not node_id and str(screen).startswith("eventlab"):
        node_id = "eventlab_events"
    node = UI_NODES.get(node_id)
    if not node:
        return UIStateDescription(active_tab=active_tab)
    return UIStateDescription(
        node_id=node.node_id,
        title=node.title,
        path=tuple(_path_titles(node.node_id)),
        tab_scope=node.tab_scope,
        active_tab=active_tab,
        tabs=node.tabs,
        options=node.options,
        children=node.children,
    )


def _path_titles(node_id: str) -> list[str]:
    titles = []
    current = UI_NODES.get(node_id)
    seen = set()
    while current and current.node_id not in seen:
        seen.add(current.node_id)
        titles.append(current.title)
        current = UI_NODES.get(current.parent)
    return list(reversed(titles))


def export_markdown(path: str | Path = "reports/ui_navigation_tree.md") -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    roots = [node for node in UI_NODES.values() if not node.parent]
    lines = [
        "# Forza Vision UI Navigation Tree",
        "",
        "This tree is a runtime recognition index. It distinguishes screen context, tab scope, selectable options, and child pages.",
        "",
    ]
    for root in roots:
        _append_node(lines, root.node_id, level=2)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _append_node(lines: list[str], node_id: str, level: int) -> None:
    node = UI_NODES[node_id]
    prefix = "#" * level
    lines.append(f"{prefix} {node.title}")
    lines.append("")
    lines.append(f"- node_id: `{node.node_id}`")
    lines.append(f"- screen: `{node.screen}`")
    if node.tab_scope:
        lines.append(f"- tab_scope: `{node.tab_scope}`")
    if node.tabs:
        lines.append("- tabs: " + " | ".join(node.tabs))
    if node.options:
        lines.append("- options: " + " | ".join(node.options))
    if node.notes:
        lines.append(f"- notes: {node.notes}")
    if node.children:
        lines.append("- child_routes:")
        for child in node.children:
            lines.append(
                f"  - `{child.trigger}` --{child.button or 'state'}--> `{child.target}`; verify: {child.verify}"
            )
    lines.append("")
    child_nodes = [candidate.node_id for candidate in UI_NODES.values() if candidate.parent == node_id]
    for child_id in child_nodes:
        _append_node(lines, child_id, level=min(level + 1, 6))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Export the Forza Vision UI navigation tree.")
    parser.add_argument("--output", default="reports/ui_navigation_tree.md")
    args = parser.parse_args(argv)
    print(export_markdown(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
