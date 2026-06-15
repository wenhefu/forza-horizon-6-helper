from __future__ import annotations


DECORATIVE_TOKENS = {
    "",
    "HORIZON",
    "HORIZON EVENTLAB",
    "HORIZONEVENTLAB",
    "FESTIVAL",
    "JAPAN",
    "ZON",
    "CR",
    "BFGOODRICH",
    "ALUMICRAFT",
    "ENTER",
    "ESC",
    "LB",
    "RB",
    "A",
    "B",
    "X",
    "Y",
    "选择",
    "返回",
    "确定",
    "取消",
    "浏览",
    "查看",
    "可用",
}


UI_NAME_RULES = {
    "pause_story_focus": [
        ("Festival Playlist / 欢迎来到日本", ("FESTIVAL", "PLAYLIST")),
        ("Festival Playlist / 欢迎来到日本", ("欢迎来到",)),
        ("开始竞赛赛事", ("开始竞赛赛事",)),
        ("开始竞赛赛事", ("开始", "赛事")),
        ("世界地图", ("世界地图",)),
        ("收集簿", ("收集簿",)),
        ("下一站", ("下一站",)),
        ("下一站", ("下一", "推荐内容")),
        ("设置", ("设置",)),
        ("退出游戏", ("退出游戏",)),
    ],
    "pause_vehicle_focus": [
        ("更换车辆", ("更换", "车辆")),
        ("购买新车", ("购买新车",)),
        ("车辆熟练度", ("熟练度", "车辆专精", "专精")),  # FH6 简中更新把"车辆熟练度"改名为"车辆专精"
        ("升级和改装车", ("升级", "改装")),
        ("调校车辆", ("调校", "车辆")),
        ("秘藏座驾", ("秘藏座驾",)),
        ("车房宝物", ("车房宝物",)),
        ("礼物掉落箱", ("礼物掉落箱",)),
        ("汽车喇叭", ("汽车喇叭",)),
    ],
    "pause_my_horizon_focus": [
        ("我的地产", ("我的地产",)),
        ("快速移动至住所", ("快速移动", "住所")),
        ("信息中心", ("信息中心",)),
        ("无人机模式", ("无人机模式",)),
        ("超级抽奖", ("SUPER", "WHEELSPIN")),
        ("超级抽奖", ("SUPEX",)),
        ("抽奖", ("抽奖",)),
        ("奖章", ("奖章",)),
    ],
    "pause_online_focus": [
        ("Horizon Open", ("HORIZON", "OPEN")),
        ("Horizon Tour", ("HORIZON", "TOUR")),
        ("Horizon Arcade", ("HORIZON", "ARCADE")),
        ("Horizon Play", ("HORIZON", "PLAY")),
        ("在线玩家列表", ("在线玩家",)),
        ("在线好友", ("在线好友",)),
        ("劲敌", ("劲敌",)),
        ("极限竞速 LINK", ("极限竞速", "LINK")),
        ("车队", ("车队",)),
    ],
    "pause_store_focus": [
        ("高级版升级捆绑包", ("高级版升级",)),
        ("Steam 商店", ("STEAM",)),
        ("车展", ("车展",)),
        ("拍卖场", ("拍卖场",)),
        ("车辆通行证", ("车辆通行证",)),
        ("车辆通行证", ("车辆通行",)),
        ("车辆包", ("车辆包",)),
        ("票券车辆", ("票券车辆",)),
    ],
    "eventlab_card_focus": [
        ("eventlab", ("eventlab",)),
        ("找不到赛事", ("找不到赛事",)),
        ("游玩赛事", ("游玩赛事",)),
        ("车库布局", ("车库布局",)),
        ("地产", ("地产",)),
        ("涂装设计", ("涂装设计",)),
        ("我的创意中心", ("我的创意中心",)),
        ("彩绘纹饰分组", ("彩绘纹饰分组",)),
        ("调校", ("调校",)),
        ("照片模式", ("照片模式",)),
        ("照片图库", ("照片图库",)),
        ("我的收藏赛事", ("我的收藏", "赛事")),
    ],
    "my_cars_card_focus": [
        ("22B", ("22B",)),
        ("我的车辆", ("我的车辆",)),
        ("Impreza 22B-STi Version", ("IMPREZA", "22B")),
    ],
    "pause_creative_hub_focus": [
        ("eventlab", ("eventlab",)),
        ("车库布局", ("车库布局",)),
        ("道具预制件", ("道具预制件",)),
        ("涂装设计", ("涂装设计",)),
        ("调校", ("调校",)),
        ("我的创意中心", ("我的创意中心",)),
        ("照片模式", ("照片模式",)),
    ],
    "modal_warning": [
        ("控制器未连接", ("控制器未连接",)),
        ("移动至嘉年华", ("移动至嘉年华",)),
        ("移动至住所", ("移动至住所",)),
        ("搜索结果", ("搜索结果",)),
        ("玩家选项", ("玩家选项",)),
        ("选择操作", ("选择操作",)),
        ("选择比赛类型", ("选择比赛类型",)),
        ("已收藏新车！", ("已收藏新车",)),
    ],
    "modal_button_focus": [
        ("嗯", ("嗯",)),
        ("不", ("不",)),
        ("是", ("是",)),
        ("否", ("否",)),
        ("确定", ("确定",)),
        ("取消", ("取消",)),
    ],
    "autoshow_menu_focus": [
        ("车展", ("车展",)),
        ("拍卖场", ("拍卖场",)),
        ("车辆通行证", ("车辆通行证",)),
        ("车辆通行证", ("车辆通行",)),
        ("车辆包", ("车辆包",)),
        ("票券车辆", ("票券车辆",)),
    ],
    "race_menu": [
        ("比赛菜单进度", ("进度",)),
    ],
    "race_result": [
        ("比赛结果车手", ("车手",)),
    ],
    "post_race_next": [
        ("霜山一日游", ("霜山一日游",)),
        ("下一站推荐", ("季节锦标赛",)),
    ],
}


def resolve_ui_name(region_name: str, text: str) -> str:
    normalized = _normalize(text)
    for official_name, required in UI_NAME_RULES.get(region_name, []):
        if all(_normalize(part) in normalized for part in required):
            return official_name
    return ""


def fallback_ui_name(text: str, *, allow_short: bool = False) -> str:
    parts = [part.strip() for part in str(text or "").replace("\n", "|").split("|")]
    for part in parts:
        cleaned = part.strip(" -:：，,。.!！?？")
        if not cleaned:
            continue
        if _normalize(cleaned) in DECORATIVE_TOKENS:
            continue
        if len(cleaned) <= 1 and not cleaned.isdigit() and not allow_short:
            continue
        return cleaned[:80]
    return ""


def _normalize(text: str) -> str:
    separators = set("|/\\_-:：,，。.!！?？·*#()（）[]【】<>《》")
    return "".join(ch for ch in str(text or "").upper() if not ch.isspace() and ch not in separators)
