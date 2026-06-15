"""Semantic page understanding for the experimental V2 recognizer.

V2 deliberately separates "what page am I looking at?" from "what should be
pressed next?".  It uses OCR text, OCR box layout, normalized coordinates, and a
small amount of color sampling.  No game files are read and no input is sent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata


PAUSE_TABS = ["剧情", "车辆", "我的地平线", "在线", "创意中心", "商店"]
EVENTLAB_TABS = ["精选", "热门", "本月最佳", "最新最热", "全新", "最爱的创作者", "我的收藏", "我的历史记录"]
AUTOSHOW_TABS = ["剧情", "购买与出售", "车辆", "角色"]

MANUFACTURER_GRID_KEYWORDS = (
    "ABARTH",
    "ALUMICRAFT",
    "AMG",
    "ARIEL",
    "AUSTIN-HEALEY",
    "AUTOZAM",
    "BAC",
    "CAN-AM",
    "GMC",
    "HOLDEN",
    "HSV",
    "SHELBY",
    "SUBARU",
    "TVR",
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
    "兰博基尼",
    "雷诺",
    "日产",
    "三菱",
    "斯巴鲁",
    "沃尔沃",
    "五菱",
    "现代",
    "雪佛兰",
    "漂移方程式",
)

STORY_FOCUS_LABELS = {
    "collection": "\u6536\u96c6\u7c3f",
    "world_map": "\u4e16\u754c\u5730\u56fe",
    "next_stop": "\u4e0b\u4e00\u7ad9",
    "settings": "\u8bbe\u7f6e",
    "exit_game": "\u9000\u51fa\u6e38\u620f",
    "festival_playlist": "Festival Playlist / \u6b22\u8fce\u6765\u5230\u65e5\u672c",
}

VEHICLE_FOCUS_REGIONS = [
    ("\u8d2d\u4e70\u65b0\u8f66\u4e0e\u4e8c\u624b\u8f66", (0.120, 0.254, 0.281, 0.822)),
    ("\u66f4\u6362\u8f66\u8f86", (0.270, 0.254, 0.773, 0.548)),
    ("\u8f66\u8f86\u719f\u7ec3\u5ea6", (0.270, 0.528, 0.582, 0.822)),
    ("\u79d8\u85cf\u5ea7\u9a7e", (0.570, 0.527, 0.732, 0.616)),
    ("\u8f66\u623f\u5b9d\u7269", (0.570, 0.596, 0.732, 0.685)),
    ("\u793c\u7269\u6389\u843d\u7bb1", (0.570, 0.665, 0.732, 0.754)),
    ("\u6c7d\u8f66\u5587\u53ed", (0.570, 0.733, 0.732, 0.822)),
    ("\u8c03\u6821\u8f66\u8f86", (0.720, 0.254, 0.882, 0.822)),
]

STORY_FOCUS_KEYWORDS = [
    (STORY_FOCUS_LABELS["collection"], ["\u6536\u96c6\u7c3f", "\u6536\u85cf\u8fdb\u5ea6"]),
    (STORY_FOCUS_LABELS["world_map"], ["\u4e16\u754c\u5730\u56fe", "\u5927\u8c37\u533a", "\u5730\u56fe"]),
    (STORY_FOCUS_LABELS["next_stop"], ["\u4e0b\u4e00\u7ad9", "\u63a8\u8350\u5185\u5bb9"]),
    (STORY_FOCUS_LABELS["settings"], ["\u8bbe\u7f6e"]),
    (STORY_FOCUS_LABELS["exit_game"], ["\u9000\u51fa\u6e38\u620f"]),
    (STORY_FOCUS_LABELS["festival_playlist"], ["FESTIVAL", "PLAYLIST", "\u6b22\u8fce\u6765\u5230", "\u65e5\u672c"]),
]

VEHICLE_FOCUS_KEYWORDS = [
    ("\u8d2d\u4e70\u65b0\u8f66\u4e0e\u4e8c\u624b\u8f66", ["\u8d2d\u4e70\u65b0\u8f66", "\u4e8c\u624b\u8f66"]),
    ("\u66f4\u6362\u8f66\u8f86", ["\u66f4\u6362\u8f66\u8f86", "\u5df2\u62e5\u6709"]),
    ("\u8f66\u8f86\u719f\u7ec3\u5ea6", ["\u8f66\u8f86\u719f\u7ec3\u5ea6", "\u6280\u672f\u70b9\u6570"]),
    ("\u79d8\u85cf\u5ea7\u9a7e", ["\u79d8\u85cf\u5ea7\u9a7e"]),
    ("\u8f66\u623f\u5b9d\u7269", ["\u8f66\u623f\u5b9d\u7269"]),
    ("\u793c\u7269\u6389\u843d\u7bb1", ["\u793c\u7269\u6389\u843d\u7bb1"]),
    ("\u6c7d\u8f66\u5587\u53ed", ["\u6c7d\u8f66\u5587\u53ed"]),
    ("\u8c03\u6821\u8f66\u8f86", ["\u8c03\u6821\u8f66\u8f86", "\u8c03\u6821\u60a8\u7684\u8f66\u8f86"]),
]


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", "", text).upper()


def has_any(normalized_text: str, keywords) -> bool:
    return any(normalize_text(keyword) in normalized_text for keyword in keywords)


def _manufacturer_hits(normalized_text: str) -> list[str]:
    return [name for name in MANUFACTURER_GRID_KEYWORDS if normalize_text(name) in normalized_text]


def _looks_like_manufacturer_grid(title_text: str, all_text: str) -> bool:
    return has_any(title_text, ["制造商"]) and len(_manufacturer_hits(all_text)) >= 4


def _looks_like_vehicle_buy_grid(all_text: str, bottom_text: str) -> bool:
    if not has_any(bottom_text, ["筛选", "排序", "前往制造商", "切换详情", "切换数据", "购买车展车辆票券"]):
        return False
    return has_any(all_text, ["购买车辆", "已拥有", "IMPREZA", "BRZ", "WRX", "斯巴鲁", "#6165", "CLASS1BUGGY"])


def _lime(r, g, b):
    return (g >= 190) & (r >= 135) & (b <= 95) & ((g - b) >= 120)


def _focus_lime(r, g, b):
    return (g >= 230) & (r >= 190) & (b <= 70) & ((g - r) >= 20) & ((g - b) >= 160)


def _dark(r, g, b):
    return (r <= 60) & (g <= 60) & (b <= 60)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


@dataclass
class SemanticItem:
    text: str
    norm: str
    confidence: float
    nx1: float
    ny1: float
    nx2: float
    ny2: float
    ncx: float
    ncy: float
    vx1: float
    vy1: float
    vx2: float
    vy2: float
    vcx: float
    vcy: float


@dataclass
class TabCandidate:
    label: str
    x: float
    y: float
    active_score: float = 0.0
    dark_score: float = 0.0
    lime_score: float = 0.0
    source_text: str = ""


@dataclass
class ActionRecommendation:
    name: str
    button: str
    reason: str
    verify: str
    confidence: float


@dataclass
class PageUnderstanding:
    screen: str
    confidence: float
    active_tab: str = ""
    selected_item: str = ""
    content_region: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    visible_tabs: list[TabCandidate] = field(default_factory=list)
    eventlab_tabs: list[TabCandidate] = field(default_factory=list)
    autoshow_tabs: list[TabCandidate] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    actions: list[ActionRecommendation] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    ocr_text: str = ""
    top_text: str = ""
    mid_text: str = ""
    bottom_text: str = ""
    item_count: int = 0

    def as_text(self) -> str:
        lines = [
            f"页面: {self.screen}  confidence={self.confidence:.2f}",
            f"当前分页: {self.active_tab or '未知'}",
            f"选中/焦点: {self.selected_item or '未知'}",
            "内容区域: "
            f"left={self.content_region[0]:.3f}, top={self.content_region[1]:.3f}, "
            f"right={self.content_region[2]:.3f}, bottom={self.content_region[3]:.3f}",
        ]
        if self.visible_tabs:
            tabs = []
            for tab in self.visible_tabs:
                marker = "*" if tab.label == self.active_tab else ""
                tabs.append(f"{marker}{tab.label}@{tab.x:.2f}/{tab.active_score:.2f}")
            lines.append("暂停分页: " + " | ".join(tabs))
        if self.eventlab_tabs:
            tabs = []
            for tab in self.eventlab_tabs:
                marker = "*" if tab.label == self.active_tab else ""
                tabs.append(f"{marker}{tab.label}@{tab.x:.2f}/{tab.active_score:.2f}")
            lines.append("EventLab分页: " + " | ".join(tabs))
        if self.screen == "autoshow_buy_sell" and self.autoshow_tabs:
            tabs = []
            for tab in self.autoshow_tabs:
                marker = "*" if tab.label == self.active_tab else ""
                tabs.append(f"{marker}{tab.label}@{tab.x:.2f}/{tab.active_score:.2f}")
            lines.append("购买与出售分页: " + " | ".join(tabs))
        if self.hints:
            lines.append("底部提示: " + " | ".join(self.hints))
        if self.actions:
            lines.append("")
            lines.append("动作建议（只展示，不执行）:")
            for action in self.actions:
                lines.append(
                    f"- {action.name}: {action.button or '不按键'} "
                    f"confidence={action.confidence:.2f}"
                )
                lines.append(f"  原因: {action.reason}")
                lines.append(f"  验证: {action.verify}")
        if self.reasons:
            lines.append("")
            lines.append("识别依据:")
            for reason in self.reasons:
                lines.append(f"- {reason}")
        lines.append("")
        lines.append(f"OCR条目: {self.item_count}")
        lines.append(f"顶部OCR: {self.top_text[:220]}")
        lines.append(f"中部OCR: {self.mid_text[:220]}")
        lines.append(f"底部OCR: {self.bottom_text[:220]}")
        return "\n".join(lines)


class ForzaSemanticAnalyzer:
    """Build a resolution-independent semantic description of a Forza screen."""

    def analyze(self, frame, ocr_items) -> PageUnderstanding:
        content_region = self._detect_content_region(frame)
        items = [self._semantic_item(item, content_region) for item in (ocr_items or [])]
        raw_text = " | ".join(item.text for item in items)
        all_text = normalize_text(raw_text)
        top_text = normalize_text(" | ".join(item.text for item in items if item.vcy <= 0.28))
        upper_text = normalize_text(" | ".join(item.text for item in items if 0.10 <= item.vcy <= 0.36))
        mid_text = normalize_text(" | ".join(item.text for item in items if 0.18 <= item.vcy <= 0.86))
        bottom_text = normalize_text(" | ".join(item.text for item in items if item.vcy >= 0.82))

        pause_tabs = self._detect_tabs(frame, content_region, items, PAUSE_TABS, 0.12, 0.32)
        eventlab_tabs = self._detect_tabs(frame, content_region, items, EVENTLAB_TABS, 0.07, 0.26)
        autoshow_tabs = self._detect_tabs(frame, content_region, items, AUTOSHOW_TABS, 0.10, 0.30)
        screen, confidence, reasons = self._infer_screen(all_text, top_text, upper_text, mid_text, bottom_text, pause_tabs)
        active_tab = self._infer_active_tab(screen, pause_tabs, eventlab_tabs, autoshow_tabs, all_text, mid_text)
        selected_item, selected_reason = self._infer_selected_item(frame, content_region, screen, mid_text, items)
        if selected_reason:
            reasons.append(selected_reason)
        hints = self._infer_hints(bottom_text)

        understanding = PageUnderstanding(
            screen=screen,
            confidence=confidence,
            active_tab=active_tab,
            selected_item=selected_item,
            content_region=content_region,
            visible_tabs=pause_tabs,
            eventlab_tabs=eventlab_tabs,
            autoshow_tabs=autoshow_tabs,
            hints=hints,
            reasons=reasons,
            ocr_text=raw_text,
            top_text=top_text,
            mid_text=mid_text,
            bottom_text=bottom_text,
            item_count=len(items),
        )
        understanding.actions = self._plan_actions(understanding)
        return understanding

    def _semantic_item(self, item, content_region):
        left, top, right, bottom = content_region
        width = max(0.001, right - left)
        height = max(0.001, bottom - top)
        nx1 = float(getattr(item, "nx1", getattr(item, "ncx", 0.5)))
        ny1 = float(getattr(item, "ny1", getattr(item, "ncy", 0.5)))
        nx2 = float(getattr(item, "nx2", getattr(item, "ncx", 0.5)))
        ny2 = float(getattr(item, "ny2", getattr(item, "ncy", 0.5)))
        ncx = float(getattr(item, "ncx", (nx1 + nx2) / 2.0))
        ncy = float(getattr(item, "ncy", (ny1 + ny2) / 2.0))
        vx1 = _clamp((nx1 - left) / width, 0.0, 1.0)
        vy1 = _clamp((ny1 - top) / height, 0.0, 1.0)
        vx2 = _clamp((nx2 - left) / width, 0.0, 1.0)
        vy2 = _clamp((ny2 - top) / height, 0.0, 1.0)
        vcx = _clamp((ncx - left) / width, 0.0, 1.0)
        vcy = _clamp((ncy - top) / height, 0.0, 1.0)
        text = str(getattr(item, "text", "") or "")
        return SemanticItem(
            text=text,
            norm=normalize_text(text),
            confidence=float(getattr(item, "confidence", 0.0) or 0.0),
            nx1=nx1,
            ny1=ny1,
            nx2=nx2,
            ny2=ny2,
            ncx=ncx,
            ncy=ncy,
            vx1=vx1,
            vy1=vy1,
            vx2=vx2,
            vy2=vy2,
            vcx=vcx,
            vcy=vcy,
        )

    def _detect_content_region(self, frame):
        if frame is None:
            return (0.0, 0.0, 1.0, 1.0)
        try:
            import numpy as np
        except Exception:
            return (0.0, 0.0, 1.0, 1.0)
        try:
            arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape((frame.height, frame.width, 4))
            rgb = arr[:, :, :3]
            brightness = rgb.max(axis=2)
            mask = brightness > 16
            row_hit = mask.mean(axis=1) > 0.02
            col_hit = mask.mean(axis=0) > 0.02
            rows = np.where(row_hit)[0]
            cols = np.where(col_hit)[0]
            if not len(rows) or not len(cols):
                return (0.0, 0.0, 1.0, 1.0)
            top = max(0, int(rows[0]) - 2) / float(frame.height)
            bottom = min(frame.height, int(rows[-1]) + 3) / float(frame.height)
            left = max(0, int(cols[0]) - 2) / float(frame.width)
            right = min(frame.width, int(cols[-1]) + 3) / float(frame.width)
            if right - left < 0.50 or bottom - top < 0.50:
                return (0.0, 0.0, 1.0, 1.0)
            return (left, top, right, bottom)
        except Exception:
            return (0.0, 0.0, 1.0, 1.0)

    def _detect_tabs(self, frame, content_region, items, labels, y_min, y_max):
        candidates = []
        for label in labels:
            label_norm = normalize_text(label)
            matches = [
                item for item in items
                if y_min <= item.vcy <= y_max and label_norm in item.norm
            ]
            if not matches:
                continue
            scored_matches = []
            for match in matches:
                dark_score, lime_score = self._tab_color_scores(frame, content_region, match)
                active_score = dark_score * 0.9 + lime_score * 2.8
                scored_matches.append((active_score, match.confidence, dark_score, lime_score, match))
            item_score = sorted(scored_matches, key=lambda scored: (scored[0], scored[1]), reverse=True)[0]
            active_score, _confidence, dark_score, lime_score, item = item_score
            candidates.append(
                TabCandidate(
                    label=label,
                    x=item.vcx,
                    y=item.vcy,
                    active_score=active_score,
                    dark_score=dark_score,
                    lime_score=lime_score,
                    source_text=item.text,
                )
            )
        return sorted(candidates, key=lambda tab: tab.x)

    def _tab_color_scores(self, frame, content_region, item):
        if frame is None:
            return 0.0, 0.0
        left, top, right, bottom = content_region
        width = max(0.001, right - left)
        height = max(0.001, bottom - top)

        def to_full(region):
            x1, y1, x2, y2 = region
            return (
                _clamp(left + x1 * width, 0.0, 1.0),
                _clamp(top + y1 * height, 0.0, 1.0),
                _clamp(left + x2 * width, 0.0, 1.0),
                _clamp(top + y2 * height, 0.0, 1.0),
            )

        pad_x = max(0.025, (item.vx2 - item.vx1) * 0.45)
        pad_y = 0.025
        tab_region = (
            _clamp(item.vx1 - pad_x, 0.0, 1.0),
            _clamp(item.vy1 - pad_y, 0.0, 1.0),
            _clamp(item.vx2 + pad_x, 0.0, 1.0),
            _clamp(item.vy2 + pad_y, 0.0, 1.0),
        )
        underline_region = (
            tab_region[0],
            _clamp(item.vy2 + 0.004, 0.0, 1.0),
            tab_region[2],
            _clamp(item.vy2 + 0.032, 0.0, 1.0),
        )
        try:
            dark_score = frame.ratio(to_full(tab_region), _dark, step=4)
            lime_score = frame.ratio(to_full(underline_region), _lime, step=2)
            return dark_score, lime_score
        except Exception:
            return 0.0, 0.0

    def _infer_screen(self, all_text, top_text, upper_text, mid_text, bottom_text, pause_tabs):
        reasons = []
        if has_any(all_text, ["季节更替", "季节将在", "秋季要来了", "春季要来了", "夏季要来了", "冬季要来了"]):
            return "notification_overlay", 0.86, ["OCR saw seasonal notification overlay"]
        if has_any(all_text, ["控制器未连接", "重新连接控制器"]):
            return "controller_disconnected", 0.98, ["OCR saw controller disconnect modal"]
        if has_any(all_text, ["请稍候", "正在下载赛事信息", "正在检查车辆限制", "正在保存"]):
            return "loading_transition", 0.86, ["OCR saw loading/wait transition"]
        if has_any(all_text, ["HORIZON", "FESTIVAL"]) and len(all_text) <= 80 and not has_any(all_text, ["KM/H", "安娜", "LINK"]):
            return "loading_transition", 0.74, ["OCR saw sparse Horizon transition screen"]
        if has_any(all_text, ["STEAM", "返回游戏", "此次会话"]) and has_any(all_text, ["退出游戏"]):
            return "external_overlay", 0.98, ["OCR saw external Steam overlay"]
        if has_any(all_text, ["不够购买额外加成", "技术点数不足", "额外加成"]):
            return "skill_points_exhausted", 0.97, ["OCR saw skill-points exhausted modal"]
        if has_any(all_text, ["移动至嘉年华", "是否要快速移动", "重新开始赛事", "所有未保存"]):
            return "modal_warning", 0.96, ["OCR saw travel/restart confirmation modal"]
        if has_any(all_text, ["是否要花费", "购买此车辆"]) and has_any(all_text, ["购买车辆", "购买车展车辆票券", "购买"]):
            return "purchase_confirm", 0.96, ["OCR saw vehicle purchase confirmation modal"]
        if has_any(all_text, ["选择操作"]) and has_any(all_text, ["上车", "添加至收藏", "查看车辆", "从车库移除车辆"]):
            return "modal_warning", 0.95, ["OCR saw vehicle action modal"]
        if has_any(all_text, ["玩家选项"]) and has_any(all_text, ["邀请加入车队", "显示玩家卡片", "举报"]):
            return "modal_warning", 0.90, ["OCR saw player options modal"]
        if has_any(all_text, ["退出拍照模式", "快照", "效果模式"]) or (
            has_any(all_text, ["隐藏界面"]) and has_any(all_text, ["拍照", "缩放", "偏角", "倾斜", "滚动"])
        ):
            return "photo_mode", 0.96, ["OCR saw photo-mode controls"]
        if has_any(all_text, ["奖励", "结算", "继续", "重开", "影响力"]) and has_any(
            all_text, ["名次", "时间", "积分", "RESULT", "REWARD"]
        ):
            return "race_result", 0.94, ["OCR saw race result/reward screen"]
        if has_any(all_text, ["已完成"]) and has_any(all_text, ["00:", "100%", "时间"]):
            return "race_result", 0.86, ["OCR saw completed-race transition"]
        if has_any(all_text, ["开始竞赛赛事", "开始赛事", "开始比赛", "赛事选项"]) and has_any(
            all_text, ["难度", "难度与设置", "车辆", "调校车辆", "蓝图", "起跑排位", "退出比赛", "单人", "合作"]
        ):
            return "race_menu", 0.92, ["OCR saw pre-race start menu"]
        if has_any(all_text, ["KM/H"]) and has_any(all_text, ["进度", "时间"]) and has_any(all_text, ["安娜", "LINK", "千米", "干米"]):
            return "race_hud", 0.96, ["OCR saw race HUD progress/time/speed"]
        if has_any(all_text, ["KM/H"]) and has_any(all_text, ["安娜", "LINK"]):
            return "free_roam_hud", 0.88, ["OCR saw free-roam HUD"]
        if has_any(all_text, ["设置"]) and has_any(all_text, ["智能车手难度", "驾驶辅助预设", "辅助功能", "控制", "视频"]):
            return "settings_menu", 0.94, ["OCR saw settings menu"]
        if has_any(all_text, ["调校"]) and has_any(all_text, ["轮胎", "齿轮", "防倾杆", "空气动力学设置", "差速器"]):
            return "tuning_menu", 0.90, ["OCR saw tuning setup page"]
        if has_any(all_text, ["在线玩家列表"]) and has_any(all_text, ["好友", "最近玩家", "邀请玩家加入车队", "车手", "状态"]):
            return "online_player_list", 0.90, ["OCR saw online player list"]
        if has_any(all_text, ["设定路线", "关闭地图", "更改筛选", "购买藏宝图"]):
            return "world_map", 0.92, ["OCR saw world map controls"]
        if has_any(all_text, ["下一站"]) and not has_any(all_text, ["世界地图", "收集簿", "退出游戏"]):
            return "post_race_next", 0.88, ["OCR saw next-stop carousel without pause-hub words"]
        if has_any(all_text, ["HORIZON", "DISCOVER", "JAPAN", "FESTIVAL"]) and has_any(all_text, ["里程碑", "腕带"]):
            return "festival_playlist", 0.90, ["OCR saw festival playlist"]
        if has_any(all_text, ["HORIZONPLAY", "HORIZON PLAY", "规格赛", "地平线竞速", "淘汰之王", "捉迷藏"]):
            return "horizon_play", 0.90, ["OCR saw Horizon Play page"]
        if _looks_like_manufacturer_grid(upper_text, all_text):
            return "manufacturer_grid", 0.93, ["OCR saw manufacturer selection grid"]
        if has_any(all_text, ["推荐设计"]) and has_any(all_text, ["出厂颜色"]) and has_any(bottom_text, ["颜色", "搜寻", "搜索"]):
            return "design_grid", 0.91, ["OCR saw recommended design grid"]
        if has_any(all_text, ["出厂颜色"]) and has_any(bottom_text, ["确定", "返回"]) and not has_any(all_text, ["推荐设计"]):
            return "color_select", 0.90, ["OCR saw factory-color selection page"]
        if has_any(bottom_text, ["更改视角"]) and has_any(all_text, ["CR", "86,000", "选择"]) and not has_any(all_text, ["购买此车辆"]):
            return "car_preview", 0.88, ["OCR saw pre-purchase car preview"]
        if has_any(all_text, ["筛选"]) and has_any(mid_text, ["收藏", "性能等级", "车辆类型"]):
            return "eventlab_filter", 0.96, ["OCR saw filter dialog fields"]
        if has_any(all_text, ["我的车辆"]) and has_any(bottom_text, ["筛选", "排序", "前往制造商", "切换详情", "切换数据"]):
            return "eventlab_my_cars", 0.92, ["OCR saw EventLab my-cars title and bottom hints"]
        if _looks_like_vehicle_buy_grid(all_text, bottom_text):
            return "vehicle_buy_grid", 0.91, ["OCR saw vehicle purchase grid and bottom controls"]
        if has_any(all_text, ["购买与出售", "车展", "拍卖场", "车辆通行证", "票券车辆"]):
            return "autoshow_buy_sell", 0.88, ["OCR saw buy/sell autoshow page"]
        if has_any(all_text, ["选择比赛类型"]) and has_any(mid_text, ["单人", "合作", "玩家对战"]):
            return "eventlab_race_type", 0.96, ["OCR saw race type dialog"]
        if has_any(all_text, ["赛事"]) and has_any(all_text, ["我的收藏"]) and has_any(all_text, ["移除最爱"]):
            return "eventlab_favorites", 0.92, ["OCR saw explicit EventLab favorites tab signals"]
        if has_any(all_text, ["赛事"]) and has_any(all_text, ["赛事选项", "查看赛事信息", "创建者信息", "最爱的赛事", "移除最爱"]):
            return "eventlab_events", 0.88, ["OCR saw selectable EventLab event-card actions"]
        if has_any(all_text, ["赛事", "找不到赛事"]) and has_any(all_text, ["最爱的创作者", "我的收藏", "我的历史记录", "全新"]):
            return "eventlab_events", 0.84, ["OCR saw empty EventLab event-list tab strip"]
        if has_any(all_text, ["赛事"]) and has_any(all_text, ["最爱的创作者", "我的收藏", "我的历史记录"]) and has_any(all_text, ["LB", "RB", "搜寻"]):
            return "eventlab_events", 0.84, ["OCR saw EventLab creator/favorites/history tabs"]
        if has_any(all_text, ["赛事"]) and has_any(all_text, ["精选", "热门", "本月最佳", "最新最热"]):
            return "eventlab_events", 0.86, ["OCR saw EventLab event-list tabs"]
        if has_any(all_text, ["EVENTLAB"]) and has_any(mid_text, ["创建", "游玩赛事", "参加挑战", "预制件"]):
            return "eventlab_home", 0.90, ["OCR saw EventLab hub menu"]
        upgrade_menu_markers = (
            "自定义升级",
            "自动升级",
            "升级预设",
            "自定义调校",
            "我的调校设置",
            "寻找调校设置",
            "已关注的玩家",
            "车辆熟练度",
            "车辆专精",
            "恢复默认升级",
        )
        if has_any(upper_text, ["升级"]) and sum(
            1 for marker in upgrade_menu_markers if has_any(all_text, [marker])
        ) >= 3:
            return "upgrade_menu", 0.92, ["OCR saw upgrade/tuning submenu"]
        mastery_markers = ("可用点数", "花费", "解锁全部", "技术分", "XP")
        if has_any(all_text, ["车辆熟练度", "车辆专精"]) and sum(1 for marker in mastery_markers if marker in all_text) >= 2:
            return "vehicle_mastery", 0.94, ["OCR saw vehicle mastery skill tree"]
        if has_any(mid_text, ["购买新车", "二手车", "更换车辆"]):
            return "pause_vehicle_entry", 0.92, ["OCR saw vehicle-page purchase/change tiles"]
        if has_any(mid_text, ["升级与调校", "我的车辆", "设计与喷漆", "车房宝物", "秘藏座驾"]):
            return "pause_vehicle", 0.90, ["OCR saw vehicle-page tuning/garage tiles"]
        if has_any(mid_text, ["EVENTLAB", "车库布局", "我的创意中心", "涂装设计"]) and has_any(all_text, ["创意中心"]):
            return "pause_creative_hub", 0.92, ["OCR saw creative-hub content"]
        if has_any(mid_text, ["我的地产", "快速移动至住所", "信息中心", "无人机模式"]):
            return "pause_my_horizon", 0.88, ["OCR saw My Horizon content"]
        if has_any(mid_text, ["HORIZONPLAY", "地平线生活", "地平线公开赛", "劲敌", "寻找车队", "组建车队"]):
            return "pause_online", 0.86, ["OCR saw online-page content"]
        if has_any(mid_text, ["世界地图", "收集簿", "下一站", "设置", "退出游戏"]):
            return "pause_story", 0.90, ["OCR saw story-page tiles"]
        if len(pause_tabs) < 3 and has_any(all_text, ["注意", "无法加入游戏", "搜索结果", "此用户尚未上传", "请稍后再试", "接受邀请"]):
            return "modal_warning", 0.94, ["OCR saw generic warning/search-result modal"]
        if len(pause_tabs) >= 3:
            return "pause_menu", 0.72, ["OCR saw enough pause top tabs"]
        return "unknown", 0.0, ["No strong semantic page match"]

    def _infer_active_tab(self, screen, pause_tabs, eventlab_tabs, autoshow_tabs, all_text, mid_text):
        page_defaults = {
            "pause_story": "剧情",
            "pause_vehicle_entry": "车辆",
            "pause_vehicle": "车辆",
            "vehicle_mastery": "车辆",
            "upgrade_menu": "车辆",
            "pause_my_horizon": "我的地平线",
            "pause_online": "在线",
            "pause_creative_hub": "创意中心",
        }
        if screen in page_defaults:
            return page_defaults[screen]
        if screen.startswith("eventlab"):
            best_eventlab = self._best_tab(eventlab_tabs)
            if best_eventlab:
                return best_eventlab.label
            if screen == "eventlab_favorites":
                return "我的收藏"
            return ""
        if screen == "autoshow_buy_sell":
            best_autoshow = self._best_tab(autoshow_tabs)
            if best_autoshow:
                return best_autoshow.label
            if has_any(all_text, ["购买与出售"]):
                return "购买与出售"
        if screen == "vehicle_buy_grid":
            return "购买车辆"
        if screen == "manufacturer_grid":
            return "制造商"
        if screen in ("design_grid", "color_select", "car_preview", "purchase_confirm"):
            return "购买车辆"
        best_pause = self._best_tab(pause_tabs)
        if best_pause:
            return best_pause.label
        if has_any(mid_text, ["EVENTLAB", "车库布局"]):
            return "创意中心"
        return ""

    def _best_tab(self, tabs):
        if not tabs:
            return None
        best = max(tabs, key=lambda tab: tab.active_score)
        if best.active_score >= 0.18:
            return best
        return None

    def _infer_selected_item(self, frame, content_region, screen, mid_text, items=None):
        if screen == "pause_story":
            label, detail = self._story_focus_from_frame(frame, content_region, items or [])
            if label:
                return label, detail
        if screen in ("pause_vehicle_entry", "pause_vehicle"):
            label, detail = self._vehicle_focus_from_frame(frame, content_region, items or [])
            if label:
                return label, detail
        if screen == "vehicle_mastery":
            for label in ("掀桌子", "解锁全部", "技能树"):
                if has_any(mid_text, [label]):
                    return label, "OCR fallback vehicle mastery selected-item match"
            return "", ""
        if screen == "autoshow_buy_sell":
            for label in ("车展", "拍卖场", "车辆通行证", "车辆包", "票券车辆"):
                if has_any(mid_text, [label]):
                    return label, "OCR fallback autoshow selected-item match"
            return "", ""
        if screen in ("vehicle_buy_grid", "manufacturer_grid"):
            label, detail = self._focused_text_from_frame(frame, content_region, items or [])
            if label:
                return label, detail
            return "", ""
        if screen == "design_grid":
            label, detail = self._focused_text_from_frame(frame, content_region, items or [])
            if label:
                return label, detail
            if has_any(mid_text, ["出厂颜色"]):
                return "出厂颜色", "OCR fallback design-grid selected-item match"
            return "", ""
        if screen == "color_select":
            return "出厂颜色", "OCR fallback color-select page title"
        if screen == "car_preview":
            joined = normalize_text(" | ".join(item.text for item in items or []))
            if "22B" in joined and "IMPREZA" in joined:
                return "IMPREZA 22B-STI VERSION", "OCR fallback car-preview vehicle match"
            return "", ""
        if screen == "purchase_confirm":
            label, detail = self._focused_text_from_frame(frame, content_region, items or [])
            if label:
                return label, detail
            return "购买", "OCR fallback purchase-confirm selected button"

        ordered = [
            ("世界地图", ["世界地图"]),
            ("收集簿", ["收集簿"]),
            ("下一站", ["下一站"]),
            ("购买新车与二手车", ["购买新车", "二手车"]),
            ("升级与调校", ["升级与调校"]),
            ("EventLab", ["EVENTLAB"]),
            ("我的收藏赛事", ["我的收藏", "移除最爱"]),
            ("开始赛事", ["开始竞赛赛事", "开始赛事"]),
            ("22B", ["22B", "2B-STI", "IMPREZA"]),
        ]
        for label, keywords in ordered:
            if has_any(mid_text, keywords):
                return label, "OCR fallback selected-item match"
        return "", ""

    def _focused_text_from_frame(self, frame, content_region, items=None):
        components = self._lime_components(
            frame,
            content_region,
            min_area=20,
            min_width=0.035,
            min_height=0.016,
            max_height=0.26,
            predicate=_focus_lime,
        )
        if not components:
            components = self._lime_components(
                frame,
                content_region,
                min_area=20,
                min_width=0.035,
                min_height=0.016,
                max_height=0.26,
                predicate=_lime,
            )
        best = None
        for area, x1, y1, x2, y2 in components[:8]:
            if y1 < 0.08 or y2 > 0.92:
                continue
            expanded = (
                _clamp(x1 - 0.020, 0.0, 1.0),
                _clamp(y1 - 0.020, 0.0, 1.0),
                _clamp(x2 + 0.020, 0.0, 1.0),
                _clamp(y2 + 0.020, 0.0, 1.0),
            )
            scored = []
            for item in items or []:
                if item.vcy < 0.08 or item.vcy > 0.92:
                    continue
                score = self._focus_item_score(item, expanded)
                if score <= 0.0:
                    continue
                scored.append((score + item.confidence * 0.04, item))
            if not scored:
                continue
            scored.sort(key=lambda row: (row[0], -row[1].vy1), reverse=True)
            top_item = scored[0][1]
            candidate = (area, top_item.text.strip(), x1, y1, x2, y2)
            if candidate[1] and (best is None or candidate[0] > best[0]):
                best = candidate
        if not best:
            return "", ""
        area, label, x1, y1, x2, y2 = best
        detail = (
            "Generic focus from lime component OCR: "
            f"{label} bbox={x1:.3f},{y1:.3f},{x2:.3f},{y2:.3f} area={area}"
        )
        return label, detail

    def _vehicle_focus_from_frame(self, frame, content_region, items=None):
        label, detail = self._vehicle_focus_component_from_frame(frame, content_region, items or [])
        if not label:
            label, score = self._focus_from_item_border_scores(
                frame,
                content_region,
                items or [],
                VEHICLE_FOCUS_KEYWORDS,
            )
            if label:
                return label, f"Vehicle focus from text-border score: {label} score={score:.3f}"
        if not label:
            label, score, runner_up = self._focus_from_region_scores(frame, content_region, VEHICLE_FOCUS_REGIONS)
            if not label:
                return "", ""
            detail = (
                "Vehicle focus from border-region score: "
                f"{label} score={score:.3f} runner_up={runner_up:.3f}"
            )
        return label, detail

    def _vehicle_focus_component_from_frame(self, frame, content_region, items=None):
        components = self._lime_components(
            frame,
            content_region,
            min_area=30,
            min_width=0.070,
            min_height=0.035,
            predicate=_focus_lime,
        )
        if not components:
            components = self._lime_components(
                frame,
                content_region,
                min_area=30,
                min_width=0.070,
                min_height=0.035,
                predicate=_lime,
            )
        best = None
        for component in components:
            area, x1, y1, x2, y2 = component
            if y1 < 0.18 or y2 > 0.88:
                continue
            label = self._label_vehicle_focus_bbox(x1, y1, x2, y2, items or [])
            if not label:
                continue
            if best is None or area > best[0]:
                best = (area, label, x1, y1, x2, y2)
        if not best:
            return "", ""
        area, label, x1, y1, x2, y2 = best
        detail = (
            "Vehicle focus from lime component: "
            f"{label} bbox={x1:.3f},{y1:.3f},{x2:.3f},{y2:.3f} area={area}"
        )
        return label, detail

    def _label_vehicle_focus_bbox(self, x1, y1, x2, y2, items=None):
        label = self._label_focus_from_items(items or [], (x1, y1, x2, y2), VEHICLE_FOCUS_KEYWORDS)
        if label:
            return label
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        height = y2 - y1
        if cx < 0.30 and height >= 0.30:
            return "\u8d2d\u4e70\u65b0\u8f66\u4e0e\u4e8c\u624b\u8f66"
        if cx > 0.70 and height >= 0.30:
            return "\u8c03\u6821\u8f66\u8f86"
        if 0.30 <= cx <= 0.75 and cy < 0.50:
            return "\u66f4\u6362\u8f66\u8f86"
        if 0.30 <= cx < 0.59 and cy >= 0.50:
            return "\u8f66\u8f86\u719f\u7ec3\u5ea6"
        if 0.56 <= cx <= 0.75 and cy >= 0.50:
            label = self._nearest_vehicle_label_from_items(
                items or [],
                cx,
                cy,
                {
                    "\u79d8\u85cf\u5ea7\u9a7e",
                    "\u8f66\u623f\u5b9d\u7269",
                    "\u793c\u7269\u6389\u843d\u7bb1",
                    "\u6c7d\u8f66\u5587\u53ed",
                },
            )
            if label:
                return label
            if cy < 0.60:
                return "\u79d8\u85cf\u5ea7\u9a7e"
            if cy < 0.667:
                return "\u8f66\u623f\u5b9d\u7269"
            if cy < 0.734:
                return "\u793c\u7269\u6389\u843d\u7bb1"
            return "\u6c7d\u8f66\u5587\u53ed"
        return ""

    def _nearest_vehicle_label_from_items(self, items, cx, cy, allowed_labels):
        best = None
        for item in items or []:
            for label in allowed_labels:
                if not has_any(item.norm, [label]):
                    continue
                distance = abs(item.vcx - cx) * 0.7 + abs(item.vcy - cy) * 1.3
                if best is None or distance < best[0]:
                    best = (distance, label)
        if best and best[0] <= 0.10:
            return best[1]
        return ""

    def _label_focus_from_items(self, items, bbox, keyword_groups):
        x1, y1, x2, y2 = bbox
        expanded = (
            _clamp(x1 - 0.025, 0.0, 1.0),
            _clamp(y1 - 0.025, 0.0, 1.0),
            _clamp(x2 + 0.025, 0.0, 1.0),
            _clamp(y2 + 0.025, 0.0, 1.0),
        )
        best = None
        for item in items or []:
            score = self._focus_item_score(item, expanded)
            if score <= 0.0:
                continue
            for label, keywords in keyword_groups:
                if not has_any(item.norm, keywords):
                    continue
                weighted = score + item.confidence * 0.05
                if best is None or weighted > best[0]:
                    best = (weighted, label)
        if best and best[0] >= 0.10:
            return best[1]
        return ""

    def _focus_from_item_border_scores(self, frame, content_region, items, keyword_groups):
        if frame is None:
            return "", 0.0
        best = None
        for item in items or []:
            matched_label = ""
            for label, keywords in keyword_groups:
                if has_any(item.norm, keywords):
                    matched_label = label
                    break
            if not matched_label:
                continue
            region = (
                _clamp(item.vx1 - 0.075, 0.0, 1.0),
                _clamp(item.vy1 - 0.055, 0.0, 1.0),
                _clamp(item.vx2 + 0.075, 0.0, 1.0),
                _clamp(item.vy2 + 0.055, 0.0, 1.0),
            )
            score = self._region_border_score(frame, content_region, region, _lime)
            score += self._region_border_score(frame, content_region, region, _focus_lime) * 0.6
            score += item.confidence * 0.02
            if best is None or score > best[0]:
                best = (score, matched_label)
        if best and best[0] >= 0.115:
            return best[1], best[0]
        return "", best[0] if best else 0.0

    def _focus_item_score(self, item, bbox):
        x1, y1, x2, y2 = bbox
        overlap_x1 = max(x1, item.vx1)
        overlap_y1 = max(y1, item.vy1)
        overlap_x2 = min(x2, item.vx2)
        overlap_y2 = min(y2, item.vy2)
        overlap = max(0.0, overlap_x2 - overlap_x1) * max(0.0, overlap_y2 - overlap_y1)
        item_area = max(0.0001, (item.vx2 - item.vx1) * (item.vy2 - item.vy1))
        overlap_ratio = overlap / item_area
        center_inside = x1 <= item.vcx <= x2 and y1 <= item.vcy <= y2
        if not center_inside and overlap_ratio <= 0.0:
            return 0.0
        bbox_cx = (x1 + x2) / 2.0
        bbox_cy = (y1 + y2) / 2.0
        distance = abs(item.vcx - bbox_cx) * 0.7 + abs(item.vcy - bbox_cy) * 1.3
        if distance > 0.26 and overlap_ratio < 0.15:
            return 0.0
        return overlap_ratio * 0.75 + max(0.0, 0.28 - distance) * 0.6

    def _focus_from_region_scores(self, frame, content_region, regions):
        if frame is None:
            return "", 0.0, 0.0
        scores = []
        for label, region in regions:
            score = self._region_border_score(frame, content_region, region, _focus_lime)
            scores.append((score, label))
        if not scores:
            return "", 0.0, 0.0
        scores.sort(reverse=True)
        best_score, best_label = scores[0]
        runner_up = scores[1][0] if len(scores) > 1 else 0.0
        if best_score < 0.10 or best_score < runner_up + 0.035:
            return "", best_score, runner_up
        return best_label, best_score, runner_up

    def _region_border_score(self, frame, content_region, region, predicate):
        left, top, right, bottom = content_region
        width = max(0.001, right - left)
        height = max(0.001, bottom - top)

        def to_full(sub_region):
            x1, y1, x2, y2 = sub_region
            return (
                _clamp(left + x1 * width, 0.0, 1.0),
                _clamp(top + y1 * height, 0.0, 1.0),
                _clamp(left + x2 * width, 0.0, 1.0),
                _clamp(top + y2 * height, 0.0, 1.0),
            )

        x1, y1, x2, y2 = region
        thickness = 0.012
        bands = [
            (x1, y1, x2, min(y2, y1 + thickness)),
            (x1, max(y1, y2 - thickness), x2, y2),
            (x1, y1, min(x2, x1 + thickness), y2),
            (max(x1, x2 - thickness), y1, x2, y2),
        ]
        try:
            return sum(frame.ratio(to_full(band), predicate, step=2) for band in bands) / len(bands)
        except Exception:
            return 0.0

    def _story_focus_from_frame(self, frame, content_region, items=None):
        components = self._lime_components(
            frame,
            content_region,
            min_area=30,
            min_width=0.070,
            min_height=0.035,
            predicate=_focus_lime,
        )
        if not components:
            components = self._lime_components(
                frame,
                content_region,
                min_area=30,
                min_width=0.070,
                min_height=0.035,
                predicate=_lime,
            )
        best = None
        for component in components:
            area, x1, y1, x2, y2 = component
            if y1 < 0.18 or y2 > 0.90:
                continue
            label = self._label_focus_from_items(items or [], (x1, y1, x2, y2), STORY_FOCUS_KEYWORDS)
            if not label:
                label = self._label_story_focus_bbox(x1, y1, x2, y2)
            if not label:
                continue
            if best is None or area > best[0]:
                best = (area, label, x1, y1, x2, y2)
        if not best:
            return "", ""
        area, label, x1, y1, x2, y2 = best
        detail = (
            "Story focus from lime component: "
            f"{label} bbox={x1:.3f},{y1:.3f},{x2:.3f},{y2:.3f} area={area}"
        )
        return label, detail

    def _lime_components(
        self,
        frame,
        content_region,
        min_area=80,
        min_width=0.045,
        min_height=0.045,
        max_height=1.0,
        predicate=_focus_lime,
    ):
        if frame is None:
            return []
        try:
            import numpy as np
        except Exception:
            return []
        try:
            arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape((frame.height, frame.width, 4))
            left, top, right, bottom = content_region
            x1 = int(_clamp(left, 0.0, 1.0) * frame.width)
            y1 = int(_clamp(top, 0.0, 1.0) * frame.height)
            x2 = int(_clamp(right, 0.0, 1.0) * frame.width)
            y2 = int(_clamp(bottom, 0.0, 1.0) * frame.height)
            if x2 - x1 < 80 or y2 - y1 < 80:
                return []
            rgb = arr[y1:y2:2, x1:x2:2, :]
            b = rgb[:, :, 0].astype(int)
            g = rgb[:, :, 1].astype(int)
            r = rgb[:, :, 2].astype(int)
            mask = predicate(r, g, b)
            height, width = mask.shape
            if height <= 0 or width <= 0:
                return []
            coords = np.argwhere(mask)
            if len(coords) == 0:
                return []
            seen = np.zeros_like(mask, dtype=bool)
            components = []
            for start_y, start_x in coords:
                if seen[start_y, start_x]:
                    continue
                stack = [(int(start_y), int(start_x))]
                seen[start_y, start_x] = True
                area = 0
                min_x = max_x = int(start_x)
                min_y = max_y = int(start_y)
                while stack:
                    cy, cx = stack.pop()
                    area += 1
                    if cx < min_x:
                        min_x = cx
                    elif cx > max_x:
                        max_x = cx
                    if cy < min_y:
                        min_y = cy
                    elif cy > max_y:
                        max_y = cy
                    for ny in (cy - 1, cy, cy + 1):
                        if ny < 0 or ny >= height:
                            continue
                        for nx in (cx - 1, cx, cx + 1):
                            if nx < 0 or nx >= width or seen[ny, nx] or not mask[ny, nx]:
                                continue
                            seen[ny, nx] = True
                            stack.append((ny, nx))
                norm_x1 = min_x / width
                norm_y1 = min_y / height
                norm_x2 = (max_x + 1) / width
                norm_y2 = (max_y + 1) / height
                norm_w = norm_x2 - norm_x1
                norm_h = norm_y2 - norm_y1
                bbox_pixels = max(1, (max_x - min_x + 1) * (max_y - min_y + 1))
                fill_ratio = area / bbox_pixels
                if area < min_area or norm_w < min_width or norm_h < min_height or norm_h > max_height:
                    continue
                if fill_ratio > 0.32:
                    continue
                components.append((area, norm_x1, norm_y1, norm_x2, norm_y2))
            return sorted(components, reverse=True)
        except Exception:
            return []

    def _largest_lime_component(self, frame, content_region):
        if frame is None:
            return None
        try:
            import numpy as np
        except Exception:
            return None
        try:
            arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape((frame.height, frame.width, 4))
            left, top, right, bottom = content_region
            x1 = int(_clamp(left, 0.0, 1.0) * frame.width)
            y1 = int(_clamp(top, 0.0, 1.0) * frame.height)
            x2 = int(_clamp(right, 0.0, 1.0) * frame.width)
            y2 = int(_clamp(bottom, 0.0, 1.0) * frame.height)
            if x2 - x1 < 80 or y2 - y1 < 80:
                return None
            rgb = arr[y1:y2:2, x1:x2:2, :]
            b = rgb[:, :, 0].astype(int)
            g = rgb[:, :, 1].astype(int)
            r = rgb[:, :, 2].astype(int)
            mask = (g >= 185) & (r >= 130) & (b <= 110) & ((g - b) >= 100)
            height, width = mask.shape
            if height <= 0 or width <= 0:
                return None

            coords = np.argwhere(mask)
            if len(coords) == 0:
                return None
            seen = np.zeros_like(mask, dtype=bool)
            best = None
            for start_y, start_x in coords:
                if seen[start_y, start_x]:
                    continue
                stack = [(int(start_y), int(start_x))]
                seen[start_y, start_x] = True
                area = 0
                min_x = max_x = int(start_x)
                min_y = max_y = int(start_y)
                while stack:
                    cy, cx = stack.pop()
                    area += 1
                    if cx < min_x:
                        min_x = cx
                    elif cx > max_x:
                        max_x = cx
                    if cy < min_y:
                        min_y = cy
                    elif cy > max_y:
                        max_y = cy
                    for ny in (cy - 1, cy, cy + 1):
                        if ny < 0 or ny >= height:
                            continue
                        for nx in (cx - 1, cx, cx + 1):
                            if nx < 0 or nx >= width or seen[ny, nx] or not mask[ny, nx]:
                                continue
                            seen[ny, nx] = True
                            stack.append((ny, nx))

                norm_x1 = min_x / width
                norm_y1 = min_y / height
                norm_x2 = (max_x + 1) / width
                norm_y2 = (max_y + 1) / height
                norm_w = norm_x2 - norm_x1
                norm_h = norm_y2 - norm_y1
                if area < 80 or norm_w < 0.045 or norm_h < 0.045:
                    continue
                if norm_y1 < 0.20 or norm_y2 > 0.90:
                    continue
                candidate = (area, norm_x1, norm_y1, norm_x2, norm_y2)
                if best is None or candidate[0] > best[0]:
                    best = candidate
            return best
        except Exception:
            return None

    def _label_story_focus_bbox(self, x1, y1, x2, y2):
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        height = y2 - y1
        if cx < 0.30 and 0.22 <= cy <= 0.86:
            return STORY_FOCUS_LABELS["collection"]
        if cx > 0.70 and 0.22 <= cy <= 0.86:
            return STORY_FOCUS_LABELS["festival_playlist"]
        if 0.30 <= cx <= 0.75 and cy < 0.54:
            return STORY_FOCUS_LABELS["world_map"]
        if 0.30 <= cx < 0.59 and cy >= 0.52:
            return STORY_FOCUS_LABELS["next_stop"]
        if 0.56 <= cx <= 0.75 and cy >= 0.52:
            if cy >= 0.73 or height <= 0.14:
                return STORY_FOCUS_LABELS["exit_game"]
            return STORY_FOCUS_LABELS["settings"]
        return ""

    def _infer_hints(self, bottom_text):
        hints = []
        hint_map = [
            ("A", ["A选择", "ENTER选择", "ENTER确定", "选择", "确定"]),
            ("B", ["B返回", "ESC返回", "返回"]),
            ("X", ["X排序", "X重置", "重置"]),
            ("X", ["X更改视角", "更改视角"]),
            ("Y", ["Y筛选", "筛选", "Y车队", "Y颜色", "颜色"]),
            ("Space", ["SPACE购买车展车辆票券", "购买车展车辆票券", "车展车辆票券"]),
            ("Back/View", ["BACKSPACE前往制造商", "前往制造商"]),
            ("Back/View", ["BACKSPACE搜寻", "BACKSPACE搜索", "搜寻", "搜索"]),
            ("P", ["P切换详情", "切换详情"]),
            ("L", ["L切换数据", "切换数据"]),
            ("RB", ["RB"]),
            ("LB", ["LB"]),
            ("Menu", ["菜单", "赛事选项"]),
        ]
        for label, keywords in hint_map:
            if has_any(bottom_text, keywords):
                hints.append(label)
        return hints

    def _plan_actions(self, understanding):
        actions = []
        if understanding.screen == "race_hud":
            actions.append(ActionRecommendation(
                "比赛中保持等待",
                "",
                "当前是赛道 HUD，不应该执行菜单导航。",
                "等待识别到结果页或赛后下一站页面。",
                0.95,
            ))
            return actions
        if understanding.screen == "race_menu":
            actions.append(ActionRecommendation(
                "赛事开始菜单",
                "",
                "当前像是 EventLab/比赛开始菜单，识别层只确认页面，不自动开始赛事。",
                "如果上层要开始比赛，按 A 后必须重新识别为 race_hud 或结果/确认页面。",
                0.90,
            ))
            return actions
        if understanding.screen == "race_result":
            actions.append(ActionRecommendation(
                "比赛结算页",
                "",
                "当前像是结算/奖励页，是否继续、重开或退出必须由上层目标决定。",
                "按键后必须重新识别到 race_menu、race_hud、post_race_next 或自由漫游 HUD。",
                0.90,
            ))
            return actions
        if understanding.screen == "post_race_next":
            actions.append(ActionRecommendation(
                "离开下一站页",
                "B",
                "赛后下一站不是暂停菜单，先返回自由漫游。",
                "按后应看到自由漫游 HUD，或能用 Menu 打开暂停菜单。",
                0.88,
            ))
            return actions
        if understanding.screen == "free_roam_hud":
            actions.append(ActionRecommendation(
                "自由漫游 HUD",
                "Menu",
                "当前不是菜单页；如果目标是进入暂停菜单，应先打开暂停菜单。",
                "按后重新识别，必须出现 pause_* 页面或 pause_menu。",
                0.80,
            ))
            return actions
        if understanding.screen == "modal_warning":
            actions.append(ActionRecommendation(
                "弹窗等待确认",
                "",
                "识别到确认/操作弹窗，V2 不知道上层意图时不建议盲按。",
                "先用 OCR 小区域确认弹窗文字；选择 A 或 B 后必须重新识别页面变化。",
                0.86,
            ))
            return actions
        if understanding.screen == "skill_points_exhausted":
            actions.append(ActionRecommendation(
                "技术点数不足",
                "A",
                "确认已经没有足够技术点数继续购买额外加成，组合流程可以关闭弹窗并转去 EventLab。",
                "按后必须重新识别到 vehicle_mastery；再逐层 B 返回自由漫游或暂停菜单。",
                0.92,
            ))
            return actions
        if understanding.screen == "loading_transition":
            actions.append(ActionRecommendation(
                "等待转场完成",
                "",
                "当前是加载/保存/下载信息转场，识别层不应发送导航输入。",
                "等待后必须重新识别到 EventLab、race_menu、race_hud、race_result 或 free_roam_hud。",
                0.86,
            ))
            return actions
        if understanding.screen == "vehicle_buy_grid":
            target_ready = has_any(normalize_text(understanding.selected_item), ["22B", "IMPREZA"])
            actions.append(ActionRecommendation(
                "购买车辆网格",
                "A" if target_ready else "",
                "当前是购买车辆/车辆选择网格；只有目标车辆已经成为焦点时才允许上层考虑 A。",
                "按后必须重新识别到购买确认、车辆详情、race_menu 或车辆网格发生预期变化；未确认目标时不按。",
                0.84 if target_ready else 0.76,
            ))
            return actions
        if understanding.screen == "manufacturer_grid":
            actions.append(ActionRecommendation(
                "制造商列表",
                "",
                "当前是制造商选择列表，识别层只确认焦点品牌和滚动状态，不盲目选择。",
                "移动焦点或选择品牌后必须重新识别到制造商列表变化或购买车辆网格品牌变化。",
                0.82,
            ))
            return actions
        if understanding.screen == "design_grid":
            actions.append(ActionRecommendation(
                "推荐设计页",
                "Y",
                "当前是购买 22B 后的推荐设计页；V1 下一步会进入出厂颜色/颜色选择，但必须确认仍在目标车辆购买路径。",
                "按后必须重新识别到颜色选择、车辆预览或仍停留在推荐设计页；若目标车辆不明则不按。",
                0.82,
            ))
            return actions
        if understanding.screen == "color_select":
            actions.append(ActionRecommendation(
                "出厂颜色选择页",
                "A",
                "当前是出厂颜色选择页；V1 下一步会确认默认颜色并进入车辆预览。",
                "按后必须重新识别到 car_preview 或购买前预览文字；未变化则等待重新识别。",
                0.84,
            ))
            return actions
        if understanding.screen == "car_preview":
            actions.append(ActionRecommendation(
                "车辆购买预览页",
                "A" if has_any(normalize_text(understanding.selected_item), ["22B", "IMPREZA"]) else "",
                "当前是最终购买确认前的车辆预览页；只有确认车辆仍是 22B 时才允许上层考虑继续。",
                "按后必须重新识别到 purchase_confirm/modal_warning，且弹窗标题应为购买车辆。",
                0.82,
            ))
            return actions
        if understanding.screen == "purchase_confirm":
            actions.append(ActionRecommendation(
                "购买确认弹窗",
                "",
                "当前已经到最终花费确认弹窗；识别层只确认按钮焦点，不自动购买。",
                "如果上层选择 A 或 B，按后必须重新识别到车辆预览、购买后展示页、加载转场或车辆网格变化。",
                0.90,
            ))
            return actions
        if understanding.screen == "notification_overlay":
            verify = "按后必须重新识别；只有出现 autoshow_buy_sell、modal_warning、pause_*、free_roam_hud 或明确菜单文字才继续。"
            actions.append(ActionRecommendation(
                "唤醒待机 UI",
                "A",
                "当前像季节通知覆盖在车辆展示/待机页上；A 通常可唤醒上下文 UI，但不能连续盲按。",
                verify,
                0.64,
            ))
            actions.append(ActionRecommendation(
                "返回/唤醒待机 UI",
                "B",
                "如果 A 后仍无 UI，B 可能返回上一层或让底部提示重新出现。",
                verify,
                0.58,
            ))
            actions.append(ActionRecommendation(
                "打开暂停菜单探针",
                "Menu",
                "如果目标是回到暂停菜单，Menu 是更明确的唤醒/开菜单探针。",
                "按后必须重新识别到 pause_*、pause_menu 或 free_roam_hud；未变化则不要连续盲按。",
                0.54,
            ))
            return actions
        if understanding.screen in (
            "external_overlay",
            "settings_menu",
            "tuning_menu",
            "online_player_list",
            "world_map",
            "festival_playlist",
            "horizon_play",
            "autoshow_buy_sell",
        ):
            actions.append(ActionRecommendation(
                "子页面/外部覆盖层",
                "",
                f"当前是 {understanding.screen}，不是暂停分页焦点页。",
                "如果要返回采样主线，按 B/Menu 后必须重新识别到 pause_* 或 free_roam_hud。",
                0.78,
            ))
            return actions
        if understanding.screen == "photo_mode":
            actions.append(ActionRecommendation(
                "退出拍照模式",
                "B/A",
                "拍照模式有独立确认，不应按买车导航键。",
                "先 B 打开退出确认；看到确认后 A 退出。",
                0.92,
            ))
            return actions
        if understanding.active_tab and understanding.active_tab in PAUSE_TABS:
            vehicle_move = self._move_between_tabs(understanding.active_tab, "车辆", PAUSE_TABS)
            creative_move = self._move_between_tabs(understanding.active_tab, "创意中心", PAUSE_TABS)
            if understanding.active_tab != "车辆":
                actions.append(ActionRecommendation(
                    "去车辆分页",
                    vehicle_move,
                    f"当前分页是 {understanding.active_tab}，目标是车辆。",
                    "按后重新识别 active_tab，必须变成车辆或车辆页内容。",
                    0.85,
                ))
            else:
                actions.append(ActionRecommendation(
                    "车辆分页已到达",
                    "",
                    "当前已经在车辆分页，不需要切分页。",
                    "下一步应确认购买/升级入口是否可见。",
                    0.90,
                ))
            if understanding.active_tab != "创意中心":
                actions.append(ActionRecommendation(
                    "去创意中心分页",
                    creative_move,
                    f"当前分页是 {understanding.active_tab}，目标是创意中心。",
                    "按后重新识别 active_tab，必须变成创意中心或出现 EventLab 内容。",
                    0.80,
                ))
            return actions
        if understanding.screen.startswith("eventlab"):
            actions.append(ActionRecommendation(
                "EventLab页面内导航",
                "按目标逐步验证",
                "当前已经在 EventLab 系列页面，应按具体目标选择 RB/A/B。",
                "每次只按一步，确认页面语义发生预期变化。",
                0.75,
            ))
            return actions
        actions.append(ActionRecommendation(
            "未知画面",
            "",
            "V2 没有足够把握，测试版不会建议盲按。",
            "请查看 OCR 分区，补充新页面规则。",
            0.0,
        ))
        return actions

    def _move_between_tabs(self, active, target, order):
        if active not in order or target not in order:
            return ""
        active_index = order.index(active)
        target_index = order.index(target)
        rb_steps = (target_index - active_index) % len(order)
        lb_steps = (active_index - target_index) % len(order)
        if rb_steps < lb_steps:
            return "RB" if rb_steps else ""
        if lb_steps < rb_steps:
            return "LB"
        return "LB" if target_index < active_index else "RB"
