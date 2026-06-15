from types import SimpleNamespace
from pathlib import Path

import pytest

from v2.semantic import ForzaSemanticAnalyzer


class LocalFrame:
    def __init__(self, width, height, bgra):
        self.width = width
        self.height = height
        self.bgra = bgra

    def iter_region(self, x1, y1, x2, y2, step=6):
        left = max(0, min(self.width - 1, int(x1 * self.width)))
        right = max(left + 1, min(self.width, int(x2 * self.width)))
        top = max(0, min(self.height - 1, int(y1 * self.height)))
        bottom = max(top + 1, min(self.height, int(y2 * self.height)))
        stride = self.width * 4
        for y in range(top, bottom, step):
            row = y * stride
            for x in range(left, right, step):
                i = row + x * 4
                b = self.bgra[i]
                g = self.bgra[i + 1]
                r = self.bgra[i + 2]
                yield r, g, b

    def ratio(self, region, predicate, step=6):
        total = 0
        matched = 0
        for pixel in self.iter_region(*region, step=step):
            total += 1
            if predicate(*pixel):
                matched += 1
        return matched / total if total else 0.0


def item(text, x=0.5, y=0.5, confidence=0.90):
    w = 0.05
    h = 0.02
    return SimpleNamespace(
        text=text,
        confidence=confidence,
        nx1=max(0.0, x - w),
        ny1=max(0.0, y - h),
        nx2=min(1.0, x + w),
        ny2=min(1.0, y + h),
        ncx=x,
        ncy=y,
    )


def story_items():
    return [
        item("\u5267\u60c5", 0.30, 0.22),
        item("\u8f66\u8f86", 0.38, 0.22),
        item("\u6211\u7684\u5730\u5e73\u7ebf", 0.47, 0.22),
        item("\u5728\u7ebf", 0.55, 0.22),
        item("\u521b\u610f\u4e2d\u5fc3", 0.62, 0.22),
        item("\u5546\u5e97", 0.69, 0.22),
        item("\u6536\u96c6\u7c3f", 0.20, 0.58),
        item("\u4e16\u754c\u5730\u56fe", 0.40, 0.38),
        item("\u4e0b\u4e00\u7ad9", 0.40, 0.62),
        item("\u8bbe\u7f6e", 0.62, 0.62),
        item("\u9000\u51fa\u6e38\u620f", 0.62, 0.78),
        item("\u6b22\u8fce\u6765\u5230\u65e5\u672c", 0.78, 0.60),
    ]


def vehicle_items():
    return [
        item("\u5267\u60c5", 0.30, 0.22),
        item("\u8f66\u8f86", 0.38, 0.22),
        item("\u6211\u7684\u5730\u5e73\u7ebf", 0.47, 0.22),
        item("\u5728\u7ebf", 0.55, 0.22),
        item("\u521b\u610f\u4e2d\u5fc3", 0.62, 0.22),
        item("\u5546\u5e97", 0.69, 0.22),
        item("\u8d2d\u4e70\u65b0\u8f66\u4e0e\u4e8c\u624b\u8f66", 0.20, 0.58),
        item("\u66f4\u6362\u8f66\u8f86", 0.42, 0.40),
        item("\u8f66\u8f86\u719f\u7ec3\u5ea6", 0.40, 0.62),
        item("\u79d8\u85cf\u5ea7\u9a7e", 0.62, 0.55),
        item("\u8f66\u623f\u5b9d\u7269", 0.62, 0.62),
        item("\u793c\u7269\u6389\u843d\u7bb1", 0.62, 0.69),
        item("\u6c7d\u8f66\u5587\u53ed", 0.62, 0.76),
        item("\u8c03\u6821\u8f66\u8f86", 0.78, 0.58),
    ]


def frame_from_local_image(path, max_width=None):
    Image = pytest.importorskip("PIL.Image")
    np = pytest.importorskip("numpy")
    image = Image.open(path).convert("RGBA")
    if max_width and image.width > max_width:
        scale = max_width / image.width
        image = image.resize((max_width, max(1, int(image.height * scale))))
    rgba = np.array(image)
    bgra = rgba[:, :, [2, 1, 0, 3]].tobytes()
    return LocalFrame(image.width, image.height, bgra)


def frame_from_pil_image(image):
    np = pytest.importorskip("numpy")
    rgba = np.array(image.convert("RGBA"))
    bgra = rgba[:, :, [2, 1, 0, 3]].tobytes()
    return LocalFrame(image.width, image.height, bgra)


def test_pause_story_with_bottom_crew_hint_still_moves_rb_to_vehicle():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("剧情", 0.30, 0.22),
            item("车辆", 0.38, 0.22),
            item("我的地平线", 0.47, 0.22),
            item("在线", 0.55, 0.22),
            item("创意中心", 0.62, 0.22),
            item("商店", 0.69, 0.22),
            item("世界地图", 0.36, 0.40),
            item("下一站", 0.42, 0.62),
            item("设置", 0.58, 0.62),
            item("Y 车队", 0.22, 0.93),
        ],
    )

    assert understanding.screen == "pause_story"
    assert understanding.active_tab == "剧情"
    vehicle_action = next(action for action in understanding.actions if action.name == "去车辆分页")
    assert vehicle_action.button == "RB"


def test_creative_hub_moves_lb_to_vehicle():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("剧情", 0.30, 0.22),
            item("车辆", 0.38, 0.22),
            item("我的地平线", 0.47, 0.22),
            item("在线", 0.55, 0.22),
            item("创意中心", 0.62, 0.22),
            item("商店", 0.69, 0.22),
            item("EVENTLAB", 0.34, 0.48),
            item("车库布局", 0.34, 0.68),
            item("涂装设计", 0.60, 0.68),
            item("拍照模式", 0.77, 0.68),
        ],
    )

    assert understanding.screen == "pause_creative_hub"
    assert understanding.active_tab == "创意中心"
    vehicle_action = next(action for action in understanding.actions if action.name == "去车辆分页")
    assert vehicle_action.button == "LB"


def test_race_hud_does_not_recommend_menu_navigation():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("进度", 0.09, 0.06),
            item("时间", 0.05, 0.14),
            item("00:04.763", 0.15, 0.14),
            item("1.2 干米", 0.50, 0.22),
            item("KM/H", 0.95, 0.85),
            item("安娜", 0.08, 0.94),
            item("LINK", 0.12, 0.94),
        ],
    )

    assert understanding.screen == "race_hud"
    assert understanding.actions[0].button == ""


def test_free_roam_hud_is_not_treated_as_unknown():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("KM/H", 0.95, 0.85),
            item("安娜", 0.08, 0.94),
            item("LINK", 0.12, 0.94),
            item("HORIZON", 0.18, 0.15),
        ],
    )

    assert understanding.screen == "free_roam_hud"
    assert understanding.actions[0].button == "Menu"
    assert understanding.actions[0].verify


def test_confirmation_modals_are_not_left_unknown():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("移动至嘉年华", 0.50, 0.42),
            item("是否要快速移动至最近的嘉年华场地？", 0.50, 0.52),
            item("选择", 0.44, 0.64),
        ],
    )

    assert understanding.screen == "modal_warning"
    assert understanding.actions[0].button == ""
    assert understanding.actions[0].verify


def test_season_notification_overlay_is_wait_only():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("季节更替", 0.50, 0.06),
            item("季节将在 09:18 后更替。秋季要来了！", 0.50, 0.12),
        ],
    )

    assert understanding.screen == "notification_overlay"
    assert [action.button for action in understanding.actions[:3]] == ["A", "B", "Menu"]
    assert understanding.actions[0].verify


def test_autoshow_buy_sell_selected_item_defaults_to_menu_row():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("购买与出售", 0.18, 0.16),
            item("车展", 0.08, 0.58),
            item("拍卖场", 0.08, 0.64),
            item("车辆通行证", 0.08, 0.70),
            item("车辆包", 0.08, 0.76),
            item("票券车辆", 0.08, 0.82),
        ],
    )

    assert understanding.screen == "autoshow_buy_sell"
    assert understanding.selected_item == "车展"
    assert understanding.actions[0].button == ""


def test_vehicle_action_modal_is_not_left_unknown():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("选择操作", 0.50, 0.28),
            item("上车", 0.50, 0.40),
            item("添加至收藏", 0.50, 0.48),
            item("查看车辆", 0.50, 0.56),
            item("从车库移除车辆", 0.50, 0.64),
        ],
    )

    assert understanding.screen == "modal_warning"


def test_settings_menu_is_identified_as_child_page():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("设置", 0.12, 0.15),
            item("智能车手难度", 0.30, 0.30),
            item("驾驶辅助预设", 0.30, 0.40),
            item("辅助功能", 0.18, 0.48),
            item("控制", 0.18, 0.56),
            item("视频", 0.18, 0.64),
        ],
    )

    assert understanding.screen == "settings_menu"
    assert understanding.actions[0].button == ""


def test_race_menu_and_result_are_identified():
    analyzer = ForzaSemanticAnalyzer()
    race_menu = analyzer.analyze(
        None,
        [
            item("开始赛事", 0.24, 0.40),
            item("赛事选项", 0.24, 0.48),
            item("难度", 0.65, 0.40),
            item("车辆", 0.65, 0.48),
        ],
    )
    result = analyzer.analyze(
        None,
        [
            item("奖励", 0.50, 0.18),
            item("继续", 0.50, 0.75),
            item("重开", 0.35, 0.75),
            item("影响力", 0.50, 0.40),
            item("名次", 0.25, 0.30),
            item("时间", 0.35, 0.30),
        ],
    )

    assert race_menu.screen == "race_menu"
    assert race_menu.actions[0].verify
    assert result.screen == "race_result"
    assert result.actions[0].button == ""


def test_eventlab_empty_and_playable_tabs_are_identified():
    analyzer = ForzaSemanticAnalyzer()
    empty_tab = analyzer.analyze(
        None,
        [
            item("赛事", 0.16, 0.16),
            item("LB", 0.30, 0.19),
            item("全新", 0.38, 0.19),
            item("最爱的创作者", 0.48, 0.19),
            item("我的收藏", 0.58, 0.19),
            item("我的历史记录", 0.68, 0.19),
            item("RB", 0.76, 0.19),
            item("找不到赛事", 0.50, 0.52),
        ],
    )
    playable_tab = analyzer.analyze(
        None,
        [
            item("赛事", 0.16, 0.16),
            item("我的收藏", 0.45, 0.19),
            item("ANYTHING GOES", 0.40, 0.42),
            item("EventLab", 0.42, 0.55),
            item("赛事选项", 0.45, 0.91),
            item("最爱的赛事", 0.55, 0.91),
            item("查看赛事信息", 0.65, 0.91),
        ],
    )

    assert empty_tab.screen == "eventlab_events"
    assert playable_tab.screen == "eventlab_events"


def test_eventlab_top_nav_uses_visual_active_tab_when_ocr_repeats_label():
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    analyzer = ForzaSemanticAnalyzer()

    image = Image.new("RGBA", (1000, 600), (30, 120, 105, 255))
    draw = ImageDraw.Draw(image)
    for left, right in ((240, 330), (350, 500), (520, 650), (660, 760), (770, 900)):
        draw.rectangle([left, 90, right, 122], fill=(245, 245, 245, 255))
    draw.rectangle([350, 90, 500, 122], fill=(0, 0, 0, 255))
    draw.rectangle([350, 122, 500, 132], fill=(190, 255, 0, 255))

    understanding = analyzer.analyze(
        frame_from_pil_image(image),
        [
            item("\u8d5b\u4e8b", 0.07, 0.12),
            item("\u672c\u6708\u6700\u4f73", 0.29, 0.17),
            item("\u70ed\u95e8", 0.43, 0.17, confidence=0.70),
            item("\u6700\u65b0\u6700\u70ed", 0.57, 0.17),
            item("\u70ed\u95e8", 0.67, 0.17, confidence=0.98),
            item("\u6211\u7684\u6536\u85cf", 0.82, 0.17),
            item("EventLab", 0.42, 0.55),
            item("\u8d5b\u4e8b\u9009\u9879", 0.45, 0.91),
            item("\u6700\u7231\u7684\u8d5b\u4e8b", 0.55, 0.91),
            item("\u67e5\u770b\u8d5b\u4e8b\u4fe1\u606f", 0.65, 0.91),
        ],
    )

    hot_tab = next(tab for tab in understanding.eventlab_tabs if tab.label == "\u70ed\u95e8")
    assert understanding.screen == "eventlab_events"
    assert understanding.active_tab == "\u70ed\u95e8"
    assert 0.38 <= hot_tab.x <= 0.48
    assert hot_tab.active_score >= 0.18


def test_eventlab_remove_favorite_hint_is_not_favorites_page():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("赛事", 0.16, 0.16),
            item("精选", 0.30, 0.19),
            item("热门", 0.42, 0.19),
            item("EventLab", 0.42, 0.55),
            item("赛事选项", 0.45, 0.91),
            item("移除最爱", 0.55, 0.91),
            item("查看赛事信息", 0.65, 0.91),
        ],
    )

    assert understanding.screen == "eventlab_events"


def test_skill_points_exhausted_modal_is_specific_state():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("不够购买额外加成", 0.50, 0.42),
            item("您的技术点数不足以解锁此额外加成。", 0.50, 0.52),
            item("确定", 0.08, 0.91),
        ],
    )

    assert understanding.screen == "skill_points_exhausted"
    assert understanding.actions[0].button == "A"


def test_upgrade_submenu_is_not_pause_story():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("升级", 0.13, 0.17),
            item("自定义升级", 0.14, 0.53),
            item("自动升级", 0.14, 0.58),
            item("升级预设", 0.14, 0.63),
            item("自定义调校", 0.14, 0.68),
            item("我的调校设置", 0.14, 0.74),
            item("寻找调校设置", 0.14, 0.79),
            item("已关注的玩家", 0.14, 0.84),
            item("车辆熟练度", 0.14, 0.89),
            item("B 返回", 0.10, 0.94),
            item("恢复默认升级/调校", 0.18, 0.94),
        ],
    )

    assert understanding.screen == "upgrade_menu"
    assert understanding.active_tab == "车辆"


def test_upgrade_submenu_and_mastery_recognized_after_车辆专精_rename():
    # FH6 简中更新把"车辆熟练度"改名为"车辆专精"; both the upgrade submenu and the mastery tree
    # must still classify so the buy-car加点 flow doesn't stall on "未看到车辆熟练度".
    analyzer = ForzaSemanticAnalyzer()
    upgrade = analyzer.analyze(
        None,
        [
            item("升级", 0.13, 0.17),
            item("自定义升级", 0.14, 0.53),
            item("自动升级", 0.14, 0.58),
            item("升级预设", 0.14, 0.63),
            item("自定义调校", 0.14, 0.68),
            item("车辆专精", 0.14, 0.89),
        ],
    )
    assert upgrade.screen == "upgrade_menu"

    mastery = analyzer.analyze(
        None,
        [
            item("车辆专精", 0.3, 0.1),
            item("可用点数", 0.3, 0.2),
            item("花费", 0.3, 0.3),
            item("抽奖精灵", 0.3, 0.4),
        ],
    )
    assert mastery.screen == "vehicle_mastery"


def test_eventlab_pre_race_competition_menu_is_race_menu():
    analyzer = ForzaSemanticAnalyzer()
    understanding = analyzer.analyze(
        None,
        [
            item("开始竞赛赛事", 0.15, 0.62),
            item("难度与设置", 0.15, 0.68),
            item("调校车辆", 0.15, 0.73),
            item("起跑排位", 0.15, 0.78),
            item("退出比赛", 0.15, 0.83),
            item("Enter 选择", 0.08, 0.92),
        ],
    )

    assert understanding.screen == "race_menu"
    assert understanding.selected_item == "开始赛事"


def test_loading_and_completed_race_transition_are_safe_states():
    analyzer = ForzaSemanticAnalyzer()
    loading = analyzer.analyze(
        None,
        [
            item("请稍候", 0.50, 0.42),
            item("正在下载赛事信息并检查车辆限制...", 0.50, 0.52),
        ],
    )
    completed = analyzer.analyze(
        None,
        [
            item("SP Farm / 24 second race = 10 skillpoints", 0.50, 0.32),
            item("已完成", 0.50, 0.42),
            item("00:36.271", 0.50, 0.50),
        ],
    )

    assert loading.screen == "loading_transition"
    assert loading.actions[0].button == ""
    assert completed.screen == "race_result"


def test_child_pages_and_player_modal_do_not_stay_unknown():
    analyzer = ForzaSemanticAnalyzer()
    tuning = analyzer.analyze(
        None,
        [
            item("调校", 0.10, 0.16),
            item("轮胎", 0.24, 0.22),
            item("齿轮", 0.32, 0.22),
            item("防倾杆", 0.40, 0.22),
            item("空气动力学设置", 0.62, 0.22),
            item("差速器", 0.72, 0.22),
        ],
    )
    player_modal = analyzer.analyze(
        None,
        [
            item("玩家选项", 0.50, 0.30),
            item("邀请加入车队", 0.50, 0.42),
            item("显示玩家卡片", 0.50, 0.54),
            item("举报", 0.50, 0.66),
        ],
    )
    player_list = analyzer.analyze(
        None,
        [
            item("在线玩家列表", 0.12, 0.16),
            item("好友", 0.32, 0.20),
            item("最近玩家", 0.44, 0.20),
            item("车手", 0.30, 0.36),
            item("状态", 0.56, 0.36),
            item("邀请玩家加入车队", 0.50, 0.90),
        ],
    )

    assert tuning.screen == "tuning_menu"
    assert tuning.actions[0].button == ""
    assert player_modal.screen == "modal_warning"
    assert player_list.screen == "online_player_list"


@pytest.mark.parametrize(
    "path, expected",
    [
        (
            Path(r"C:/Users/fu/Videos/Captures/Screenshot 2026_5_27 23_33_29.png"),
            "\u6536\u96c6\u7c3f",
        ),
        (
            Path(r"C:/Users/fu/Videos/Captures/Forza Horizon 6 2026_5_27 23_33_31.png"),
            "\u4e16\u754c\u5730\u56fe",
        ),
        (
            Path(r"C:/Users/fu/Videos/Captures/Forza Horizon 6 2026_5_27 23_33_33.png"),
            "\u4e0b\u4e00\u7ad9",
        ),
        (
            Path(r"C:/Users/fu/Videos/Captures/Forza Horizon 6 2026_5_27 23_33_34.png"),
            "\u8bbe\u7f6e",
        ),
        (
            Path(r"C:/Users/fu/Videos/Captures/Forza Horizon 6 2026_5_27 23_33_55.png"),
            "\u9000\u51fa\u6e38\u620f",
        ),
        (
            Path(r"C:/Users/fu/Videos/Captures/Forza Horizon 6 2026_5_27 23_33_57.png"),
            "Festival Playlist / \u6b22\u8fce\u6765\u5230\u65e5\u672c",
        ),
    ],
)
def test_pause_story_focus_uses_lime_border_from_local_calibration_images(path, expected):
    if not path.exists():
        pytest.skip(f"local calibration image is missing: {path}")
    analyzer = ForzaSemanticAnalyzer()
    frame = frame_from_local_image(path)
    understanding = analyzer.analyze(frame, story_items())

    assert understanding.screen == "pause_story"
    assert understanding.selected_item == expected


_CAPTURES = Path(r"C:/Users/fu/Videos/Captures")
_VEHICLE_BUY_IMAGE = next(_CAPTURES.glob("*5_46_45.png"), _CAPTURES / "missing-5_46_45.png")


@pytest.mark.parametrize(
    "path, expected",
    [
        (
            _VEHICLE_BUY_IMAGE,
            "\u8d2d\u4e70\u65b0\u8f66\u4e0e\u4e8c\u624b\u8f66",
        ),
        (
            _CAPTURES / "Forza Horizon 6 2026_5_28 5_46_47.png",
            "\u66f4\u6362\u8f66\u8f86",
        ),
        (
            _CAPTURES / "Forza Horizon 6 2026_5_28 5_46_49.png",
            "\u8f66\u8f86\u719f\u7ec3\u5ea6",
        ),
        (
            _CAPTURES / "Forza Horizon 6 2026_5_28 5_46_50.png",
            "\u79d8\u85cf\u5ea7\u9a7e",
        ),
        (
            _CAPTURES / "Forza Horizon 6 2026_5_28 5_46_52.png",
            "\u8f66\u623f\u5b9d\u7269",
        ),
        (
            _CAPTURES / "Forza Horizon 6 2026_5_28 5_46_53.png",
            "\u793c\u7269\u6389\u843d\u7bb1",
        ),
        (
            _CAPTURES / "Forza Horizon 6 2026_5_28 5_46_55.png",
            "\u6c7d\u8f66\u5587\u53ed",
        ),
        (
            _CAPTURES / "Forza Horizon 6 2026_5_28 5_46_56.png",
            "\u8c03\u6821\u8f66\u8f86",
        ),
    ],
)
def test_pause_vehicle_focus_uses_lime_border_from_local_calibration_images(path, expected):
    if not path.exists():
        pytest.skip(f"local calibration image is missing: {path}")
    analyzer = ForzaSemanticAnalyzer()
    frame = frame_from_local_image(path)
    understanding = analyzer.analyze(frame, vehicle_items())

    assert understanding.screen == "pause_vehicle_entry"
    assert understanding.active_tab == "\u8f66\u8f86"
    assert understanding.selected_item == expected


@pytest.mark.parametrize(
    "path, expected",
    [
        (_VEHICLE_BUY_IMAGE, "\u8d2d\u4e70\u65b0\u8f66\u4e0e\u4e8c\u624b\u8f66"),
        (_CAPTURES / "Forza Horizon 6 2026_5_28 5_46_47.png", "\u66f4\u6362\u8f66\u8f86"),
        (_CAPTURES / "Forza Horizon 6 2026_5_28 5_46_49.png", "\u8f66\u8f86\u719f\u7ec3\u5ea6"),
        (_CAPTURES / "Forza Horizon 6 2026_5_28 5_46_50.png", "\u79d8\u85cf\u5ea7\u9a7e"),
        (_CAPTURES / "Forza Horizon 6 2026_5_28 5_46_52.png", "\u8f66\u623f\u5b9d\u7269"),
        (_CAPTURES / "Forza Horizon 6 2026_5_28 5_46_53.png", "\u793c\u7269\u6389\u843d\u7bb1"),
        (_CAPTURES / "Forza Horizon 6 2026_5_28 5_46_55.png", "\u6c7d\u8f66\u5587\u53ed"),
        (_CAPTURES / "Forza Horizon 6 2026_5_28 5_46_56.png", "\u8c03\u6821\u8f66\u8f86"),
    ],
)
def test_pause_vehicle_focus_survives_small_window_scaling(path, expected):
    if not path.exists():
        pytest.skip(f"local calibration image is missing: {path}")
    analyzer = ForzaSemanticAnalyzer()
    frame = frame_from_local_image(path, max_width=760)
    understanding = analyzer.analyze(frame, vehicle_items())

    assert understanding.screen == "pause_vehicle_entry"
    assert understanding.selected_item == expected
