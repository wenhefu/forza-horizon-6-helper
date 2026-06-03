from types import SimpleNamespace
import threading
import time

from v4.decision import (
    BuyContext,
    RouteContext,
    decide_buy_loop,
    decide_farm_loop,
    decide_mode3_navigation,
    is_22b,
    is_target_event,
    normalize_button,
)
from v4.farm_runner import VisionFarmRunner
from v4.mode3_runner import V4Mode3Runner
from v4.watchdog import ProgressWatchdog


def fake_v3(
    screen,
    active_tab="",
    selected_item="",
    confidence=0.90,
    actions=None,
    filter_state=None,
    scroll_state=None,
    ocr_regions=None,
):
    return SimpleNamespace(
        screen=screen,
        active_tab=active_tab,
        selected_item=selected_item,
        confidence=confidence,
        actions=actions or [],
        filter_state=filter_state or {},
        scroll_state=scroll_state or {},
        ocr_regions=ocr_regions or [],
    )


def test_farm_loop_starts_race_only_when_focus_on_start():
    start = decide_farm_loop(fake_v3("race_menu", selected_item="开始赛事"))
    assert start.name == "farm_start_race" and normalize_button(start.button) == "a"
    # Focus not on start -> WAIT, never DpadUp (in-race DpadUp opens Photo Mode).
    wrong = decide_farm_loop(fake_v3("race_menu", selected_item="退出比赛"))
    assert wrong.name == "farm_wait_race_menu_focus" and normalize_button(wrong.button) == ""


def test_farm_loop_never_emits_dpad_up():
    # DpadUp is unsafe in the farm loop (in-race == Photo Mode). No farm state
    # should ever decide DpadUp.
    screens = [
        "race_menu", "prestart", "race_hud", "race_result", "post_race_next",
        "race_pause_menu", "pause_story", "pause_menu", "controller_disconnected",
        "loading_transition", "idle_showcase", "unknown",
    ]
    for screen in screens:
        for graceful in (False, True):
            d = decide_farm_loop(fake_v3(screen, selected_item="退出比赛"), graceful_exit=graceful)
            assert normalize_button(d.button) != "dpad_up", f"{screen} emitted DpadUp"


def test_farm_loop_holds_throttle_in_race_hud():
    drive = decide_farm_loop(fake_v3("race_hud"))
    assert drive.name == "race_drive_throttle"
    assert normalize_button(drive.button) == ""


def test_farm_loop_restart_vs_graceful_on_results():
    restart = decide_farm_loop(fake_v3("race_result", selected_item="22B"), graceful_exit=False)
    assert restart.name == "farm_restart_results" and normalize_button(restart.button) == "x"
    graceful = decide_farm_loop(fake_v3("race_result"), graceful_exit=True)
    assert graceful.name == "farm_graceful_exit_results" and normalize_button(graceful.button) == "a"


def test_farm_loop_confirm_restart_modal_or_cancel_when_graceful():
    confirm = decide_farm_loop(fake_v3("modal_warning", selected_item="确定要重新开始赛事吗"), graceful_exit=False)
    assert confirm.name == "farm_confirm_restart" and normalize_button(confirm.button) == "a"
    cancel = decide_farm_loop(fake_v3("modal_warning", selected_item="确定要重新开始赛事吗"), graceful_exit=True)
    assert cancel.name == "farm_cancel_restart" and normalize_button(cancel.button) == "b"


def test_farm_loop_confirms_unknown_popup_to_proceed_into_race():
    # Regression (2026-05-30): a popup that is NOT the explicit 重新开始赛事 modal
    # used to fall through to farm_wait_unknown, so the runner just waited and the
    # race never auto-started after buying ("买完车后不会自动刷图"). Any farm-context
    # popup should press A to proceed into the race (B only while gracefully exiting).
    proceed = decide_farm_loop(fake_v3("modal_warning", selected_item="赛事提示"), graceful_exit=False)
    assert proceed.name == "farm_confirm_modal" and normalize_button(proceed.button) == "a"
    leaving = decide_farm_loop(fake_v3("modal_warning", selected_item="赛事提示"), graceful_exit=True)
    assert normalize_button(leaving.button) == "b"


def test_farm_loop_post_race_is_terminal_only_when_graceful():
    normal = decide_farm_loop(fake_v3("post_race_next"), graceful_exit=False)
    assert normal.name == "farm_leave_post_race" and normalize_button(normal.button) == "b"
    assert normal.terminal is False
    assert decide_farm_loop(fake_v3("post_race_next"), graceful_exit=True).terminal is True


def test_farm_loop_returns_b_from_pause_states():
    assert normalize_button(decide_farm_loop(fake_v3("race_pause_menu", selected_item="世界地图")).button) == "b"
    assert normalize_button(decide_farm_loop(fake_v3("pause_story", selected_item="世界地图")).button) == "b"


def test_farm_loop_starts_race_even_when_start_menu_reads_as_pause_story():
    # The EventLab race start menu sometimes mis-reads as pause_story; the
    # focused tile text ("开始竞赛赛事") is the reliable signal to press A.
    misread = decide_farm_loop(fake_v3("pause_story", selected_item="开始竞赛赛事"))
    assert misread.name == "farm_start_race" and normalize_button(misread.button) == "a"
    # but a normal pause (world-map focus) must still back out with B.
    normal = decide_farm_loop(fake_v3("pause_story", selected_item="世界地图"))
    assert normal.name == "farm_return_from_pause" and normalize_button(normal.button) == "b"


def test_farm_loop_dismisses_controller_modal():
    d = decide_farm_loop(fake_v3("controller_disconnected", selected_item="控制器未连接"))
    assert d.name == "farm_dismiss_controller" and normalize_button(d.button) == "a"


def test_farm_loop_waits_without_pressing_on_loading_and_unknown():
    assert decide_farm_loop(fake_v3("loading_transition")).name == "farm_wait_loading"
    assert normalize_button(decide_farm_loop(fake_v3("loading_transition")).button) == ""
    assert decide_farm_loop(fake_v3("unknown")).name == "farm_wait_unknown"
    assert normalize_button(decide_farm_loop(fake_v3("idle_showcase")).button) == ""


def test_v4_runner_defaults_to_vision_farm_and_shares_recognizer():
    runner = V4Mode3Runner(title="Forza")
    assert runner._farm_mode == "vision"
    assert runner.vision_farm_runner is not None
    # share one recognizer instance so the ONNX model is not loaded twice
    assert runner.vision_farm_runner.recognizer is runner.recognizer


def test_buy_monitor_uses_full_ocr_so_car_grids_are_not_misread():
    # Regression (2026-05-30): the buy monitor MUST use full OCR. With
    # full_ocr=False the detector/rules misread dense car grids
    # (制造商列表 / 斯巴鲁车展 / 购买车辆页) as eventlab_my_cars -- they share the
    # same card-grid structure -- which tripped _buy_phase_can_handoff_to_v4 and
    # aborted BuyCarRunner mid-flow, so the car was never bought (user hit this
    # twice). Full OCR keeps them classified as vehicle_buy_grid/manufacturer_grid
    # (owned screens -> no handoff). The monitor only ticks every ~watchdog/10s,
    # so full OCR here is essentially free. Do NOT "speed this up" to full_ocr=False.
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    snapshot = SimpleNamespace(v3=fake_v3("vehicle_buy_grid"), smart_state="", elapsed_ms=1.0)
    calls = []
    runner._recognize = lambda **kwargs: (calls.append(kwargs) or snapshot)

    assert V4Mode3Runner._recognize_buy_monitor(runner) is snapshot
    assert calls == [{"full_ocr": True, "region_ocr": True}]


def test_buy_monitor_accepts_legacy_no_arg_recognize_mocks():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    snapshot = SimpleNamespace(v3=fake_v3("vehicle_buy_grid"), smart_state="", elapsed_ms=1.0)
    runner._recognize = lambda: snapshot

    assert V4Mode3Runner._recognize_buy_monitor(runner) is snapshot


def test_farm_smart_hint_overrides_false_race_menu_to_hud():
    runner = VisionFarmRunner.__new__(VisionFarmRunner)
    snapshot = SimpleNamespace(
        v3=fake_v3("race_menu", selected_item="", confidence=0.91),
        smart_state="racing",
        smart_confidence=0.92,
    )

    out = VisionFarmRunner._apply_smart_farm_hint(runner, snapshot)
    assert out.v3.screen == "race_hud"
    assert decide_farm_loop(out.v3).name == "race_drive_throttle"


def test_farm_smart_hint_can_start_prestart_without_full_ocr():
    runner = VisionFarmRunner.__new__(VisionFarmRunner)
    snapshot = SimpleNamespace(
        v3=fake_v3("unknown", selected_item="", confidence=0.0),
        smart_state="prestart",
        smart_confidence=0.93,
    )

    out = VisionFarmRunner._apply_smart_farm_hint(runner, snapshot)
    assert out.v3.screen == "race_menu"
    assert decide_farm_loop(out.v3).name == "farm_start_race"


def test_run_loop_retries_after_failure_then_completes():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(stopped_reason="ok")
    runner._log = lambda m: None
    runner._sleep = lambda s: True
    runner._pad_provider = lambda: None
    runner._recover_between_rounds = lambda pad: True
    runner._loop_rounds = lambda v: 2
    runner._farm_seconds = lambda f: 180.0
    seq = iter([False, True, True])  # round 1 fails, then two successful rounds
    runner.run_once = lambda **k: next(seq)
    ok = V4Mode3Runner.run_loop(
        runner, run_buy=True, run_farm=True, exit_after_farm=True, loop_rounds=2, max_consecutive_failures=3
    )
    assert ok is True


def test_run_loop_stops_after_max_consecutive_failures():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(stopped_reason="buy_phase_failed")
    runner._log = lambda m: None
    runner._sleep = lambda s: True
    runner._pad_provider = lambda: None
    recovered = []
    runner._recover_between_rounds = lambda pad: bool(recovered.append(1)) or True
    runner._loop_rounds = lambda v: None  # infinite
    runner._farm_seconds = lambda f: 180.0
    runner.run_once = lambda **k: False  # always fails
    ok = V4Mode3Runner.run_loop(
        runner, run_buy=True, run_farm=True, exit_after_farm=True, loop_rounds=0, max_consecutive_failures=3
    )
    assert ok is False
    assert len(recovered) == 2  # recovers after failures 1 and 2; the 3rd failure stops it


def test_run_loop_auto_enables_exit_after_farm_instead_of_degrading():
    # Regression (2026-05-30): loop_rounds=0 (infinite) with the post-farm
    # cleanup unchecked used to silently degrade to a SINGLE round and stop,
    # which surprised the user ("不是0吗 一直循环吗"). A loop MUST auto-enable
    # exit_after_farm (so each round returns to a known pause-menu start) and
    # keep looping instead of running once.
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(stopped_reason="ok")
    runner._log = lambda m: None
    runner._sleep = lambda s: True
    runner._pad_provider = lambda: None
    runner._recover_between_rounds = lambda pad: True
    runner._loop_rounds = lambda v: 2
    runner._farm_seconds = lambda f: 180.0
    seen = []
    runner.run_once = lambda **k: (seen.append(k.get("exit_after_farm")) or True)
    ok = V4Mode3Runner.run_loop(
        runner, run_buy=True, run_farm=True, exit_after_farm=False, loop_rounds=2, max_consecutive_failures=3
    )
    assert ok is True
    assert len(seen) == 2  # looped twice, did NOT degrade to a single round
    assert all(v is True for v in seen)  # cleanup auto-enabled so rounds can chain


def test_buy_loop_terminal_on_skill_points_exhausted():
    d = decide_buy_loop(fake_v3("skill_points_exhausted", selected_item="不够购买额外加成"))
    assert d.name == "buy_phase_done" and d.terminal is True
    assert normalize_button(d.button) == ""


def test_buy_loop_never_confirms_purchase_unless_22b_armed():
    unarmed = decide_buy_loop(fake_v3("purchase_confirm", selected_item="购买车辆"), BuyContext(purchase_armed=False))
    assert unarmed.name == "buy_cancel_unconfirmed_purchase" and normalize_button(unarmed.button) == "b"
    armed = decide_buy_loop(fake_v3("purchase_confirm", selected_item="购买车辆"), BuyContext(purchase_armed=True))
    assert armed.name == "buy_confirm_purchase" and normalize_button(armed.button) == "a"


def test_buy_loop_backs_out_of_preview_color_design_when_unarmed():
    # Safety: never advance a purchase from preview/color/design unless 22B armed.
    for screen in ("car_preview", "color_select", "design_grid"):
        d = decide_buy_loop(fake_v3(screen, selected_item="IMPREZA 22B-STI VERSION"), BuyContext(purchase_armed=False))
        assert normalize_button(d.button) == "b", f"{screen} must back out when unarmed"


def test_buy_loop_selects_22b_else_scans():
    on22b = decide_buy_loop(fake_v3("vehicle_buy_grid", selected_item="IMPREZA 22B-STI VERSION"))
    assert on22b.name == "buy_select_22b" and normalize_button(on22b.button) == "a"
    other = decide_buy_loop(fake_v3("vehicle_buy_grid", selected_item="BRZ"))
    assert other.name == "buy_scan_vehicle_grid" and normalize_button(other.button) == "dpad_right"


def test_buy_loop_manufacturer_and_vehicle_entry():
    sub = decide_buy_loop(fake_v3("manufacturer_grid", selected_item="斯巴鲁"))
    assert sub.name == "buy_enter_subaru" and normalize_button(sub.button) == "a"
    entry = decide_buy_loop(fake_v3("pause_vehicle_entry", selected_item="购买新车与二手车"))
    assert entry.name == "buy_enter_purchase_menu" and normalize_button(entry.button) == "a"


def test_button_mapping_accepts_v3_labels():
    assert normalize_button("A") == "a"
    assert normalize_button("Menu") == "start"
    assert normalize_button("DPadUp") == "dpad_up"
    assert normalize_button("Back/View") == "back"


def test_target_matchers_cover_mode3_goal_names():
    assert is_target_event("SP Farm / 24 second race = 10 skillpoints")
    assert is_22b("IMPREZA 22B-STI VERSION")
    assert is_22b("MPREZA 22B-STI VERSI...")


def test_filter_unchecked_toggles_once_checked_returns():
    unchecked = decide_mode3_navigation(
        fake_v3(
            "eventlab_filter",
            filter_state={"visible": True, "focused_row": "收藏", "favorite_checked": False},
        ),
        RouteContext(),
    )
    assert unchecked.button == "A"
    assert "勾选" in unchecked.reason

    checked = decide_mode3_navigation(
        fake_v3(
            "eventlab_filter",
            filter_state={"visible": True, "focused_row": "收藏", "favorite_checked": True},
        ),
        RouteContext(),
    )
    assert checked.button == "B"
    assert "取消" in checked.reason


def _order_runner(calls):
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner._stop = threading.Event()
    runner.title = "Forza"
    runner.report_dir = SimpleNamespace(mkdir=lambda **k: None)
    runner._log = lambda m: None
    runner._sleep = lambda s: True
    runner._pad_provider = lambda: SimpleNamespace(neutral=lambda: None)
    runner._ensure_foreground = lambda *a, **k: True
    runner._farm_seconds = lambda f: 1.0
    runner.write_report = lambda: None
    runner._finish = lambda ok, reason: ok
    runner._run_buy_phase = lambda **k: (calls.append("buy") or True)
    runner._navigate = lambda *a, **k: (calls.append("nav") or True)
    runner._run_farm_phase = lambda *a, **k: (calls.append("farm") or True)
    runner._exit_after_farm = lambda *a, **k: (calls.append("exit") or True)
    return runner


def test_run_once_buy_first_phase_order():
    calls = []
    ok = _order_runner(calls).run_once(run_buy=True, run_farm=True, exit_after_farm=True, buy_first=True)
    assert ok is True
    assert calls == ["buy", "nav", "farm", "exit"]


def test_run_once_farm_first_phase_order():
    # 先跑图再买车：导航 -> 刷图 -> 收尾回暂停 -> 买车（买车在最后，从干净起点开始）。
    calls = []
    ok = _order_runner(calls).run_once(run_buy=True, run_farm=True, exit_after_farm=True, buy_first=False)
    assert ok is True
    assert calls == ["nav", "farm", "exit", "buy"]


def test_run_once_farm_first_forces_exit_before_buy_even_when_unchecked():
    # Even if the user unchecked post-farm cleanup, farm-first MUST return to the pause
    # menu before buying so the buy phase starts from a clean, known page.
    calls = []
    ok = _order_runner(calls).run_once(run_buy=True, run_farm=True, exit_after_farm=False, buy_first=False)
    assert ok is True
    assert calls == ["nav", "farm", "exit", "buy"]


def test_eventlab_uses_top_nav_not_y_for_favorites():
    decision = decide_mode3_navigation(
        fake_v3("eventlab_events", active_tab="热门", selected_item="dao ju4"),
        RouteContext(),
    )
    assert decision.button in {"LB", "RB"}
    assert "Y" in decision.reason


def test_eventlab_does_not_enter_wrong_event():
    context = RouteContext(eventlab_card_moves=8)
    decision = decide_mode3_navigation(
        fake_v3("eventlab_favorites", active_tab="我的收藏", selected_item="dao ju4"),
        context,
    )
    assert decision.button == ""
    assert decision.name == "target_event_not_found"


def test_eventlab_tab_unknown_nudges_to_favorites_then_waits_patiently():
    # Network glitch: the events grid is still loading so the tab bar reads as unknown.
    # V4 must NOT freeze + fail -- it nudges RB toward 我的收藏 (bounded), then waits patiently.
    nudging = decide_mode3_navigation(
        fake_v3("eventlab_events", active_tab="", selected_item="某个非目标赛事"),
        RouteContext(eventlab_tab_unknown_nudges=0),
    )
    assert nudging.name == "nudge_eventlab_tab_to_favorites"
    assert normalize_button(nudging.button) == "rb"

    waiting = decide_mode3_navigation(
        fake_v3("eventlab_events", active_tab="", selected_item="某个非目标赛事"),
        RouteContext(eventlab_tab_unknown_nudges=4),
    )
    assert waiting.name == "eventlab_tab_unknown_wait"
    assert waiting.can_press is False  # patient wait, never a blind press


def test_eventlab_target_event_and_22b_are_enterable():
    event = decide_mode3_navigation(
        fake_v3("eventlab_favorites", active_tab="我的收藏", selected_item="SP Farm / 24 second race = 10 skillpoints"),
        RouteContext(),
    )
    assert event.button == "A"

    car = decide_mode3_navigation(
        fake_v3("eventlab_my_cars", selected_item="IMPREZA 22B-STI VERSION"),
        RouteContext(favorite_filter_done=True),
    )
    assert car.button == "A"


def test_eventlab_my_cars_requires_favorite_filter_before_selecting_22b():
    decision = decide_mode3_navigation(
        fake_v3("eventlab_my_cars", selected_item="IMPREZA 22B-STI VERSION"),
        RouteContext(favorite_filter_done=False),
    )
    assert decision.name == "open_vehicle_favorite_filter"
    assert decision.button == "Y"


def test_race_hud_is_terminal_navigation_success():
    decision = decide_mode3_navigation(fake_v3("race_hud"), RouteContext())
    assert decision.name == "arrived_race_hud"
    assert decision.terminal
    assert decision.button == ""


def test_race_pause_menu_returns_to_existing_race_not_locked_tiles():
    decision = decide_mode3_navigation(fake_v3("race_pause_menu", selected_item="赛事暂停菜单（带锁功能）"), RouteContext())
    assert decision.name == "resume_from_race_pause_menu"
    assert decision.button == "B"
    assert "带锁" in decision.reason


def test_upgrade_submenu_backs_out_instead_of_switching_pause_tabs():
    decision = decide_mode3_navigation(
        fake_v3("upgrade_menu", active_tab="车辆", selected_item="车辆熟练度"),
        RouteContext(),
    )
    assert decision.name == "back_out_from_buy_flow"
    assert decision.button == "B"


def test_autoshow_child_pages_back_out_during_eventlab_navigation():
    for screen in (
        "autoshow_buy_sell",
        "autoshow_showroom",
        "vehicle_buy_grid",
        "manufacturer_grid",
        "design_grid",
        "color_select",
        "car_preview",
        "purchase_confirm",
        "garage_my_cars",
    ):
        decision = decide_mode3_navigation(fake_v3(screen, selected_item="not route"), RouteContext())
        assert decision.name == "back_out_from_buy_flow"
        assert decision.button == "B"


def test_buy_phase_owns_upgrade_and_autoshow_children():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    for screen in ("upgrade_menu", "autoshow_buy_sell", "vehicle_buy_grid", "purchase_confirm"):
        snapshot = SimpleNamespace(
            smart_state="prestart",
            smart_confidence=0.95,
            v3=fake_v3(screen, selected_item="not route", confidence=0.90),
        )
        assert not V4Mode3Runner._buy_phase_can_handoff_to_v4(runner, snapshot)


def test_eventlab_home_requires_confirmed_eventlab_focus():
    mismatch = decide_mode3_navigation(
        fake_v3("eventlab_home", active_tab="在线", selected_item="Horizon Play"),
        RouteContext(),
    )
    assert mismatch.button == ""
    assert mismatch.name == "eventlab_home_pause_tab_mismatch"

    unknown_focus = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item=""),
        RouteContext(),
    )
    assert unknown_focus.button == ""
    assert unknown_focus.name == "eventlab_home_focus_unknown"

    garage_layout = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="车库布局"),
        RouteContext(),
    )
    assert garage_layout.name == "move_creative_focus_to_eventlab"
    assert garage_layout.button == "DPadUp"

    confirmed = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="eventlab"),
        RouteContext(),
    )
    assert confirmed.button == "A"

    browse_events = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="浏览赛事"),
        RouteContext(),
    )
    assert browse_events.name == "enter_eventlab_events"
    assert browse_events.button == "A"

    play_events = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="游玩赛事"),
        RouteContext(),
    )
    assert play_events.name == "enter_eventlab_events"
    assert play_events.button == "A"


def test_locked_feature_modal_closes_known_ok_once():
    decision = decide_mode3_navigation(
        fake_v3("modal_warning", active_tab="在线", selected_item="功能尚未解锁"),
        RouteContext(),
    )
    assert decision.name == "close_locked_feature_modal"
    assert decision.button == "A"


def test_restart_event_modal_confirms_once():
    decision = decide_mode3_navigation(
        fake_v3("modal_warning", selected_item="重新开始赛事"),
        RouteContext(),
    )
    assert decision.name == "confirm_restart_event"
    assert decision.button == "A"


def test_eventlab_home_does_not_retry_after_locked_modal():
    decision = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="eventlab"),
        RouteContext(locked_feature_seen=True),
    )
    assert decision.name == "back_out_after_locked_feature"
    assert decision.button == "B"

    after_backouts = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="eventlab"),
        RouteContext(locked_feature_seen=True, locked_backouts=2),
    )
    assert after_backouts.name == "eventlab_locked_after_retry"
    assert after_backouts.button == ""


def test_creative_hub_does_not_reenter_locked_eventlab():
    decision = decide_mode3_navigation(
        fake_v3("pause_creative_hub", active_tab="创意中心", selected_item="eventlab"),
        RouteContext(locked_feature_seen=True),
    )
    assert decision.name == "eventlab_feature_locked"
    assert decision.button == ""


def test_watchdog_tracks_progress_and_stall():
    watchdog = ProgressWatchdog(timeout_seconds=0.01, max_recoveries=1)
    assert watchdog.observe("route", "a") is True
    assert watchdog.observe("route", "a") is False
    import time

    time.sleep(0.02)
    assert watchdog.stalled()
    assert watchdog.can_recover()
    watchdog.note_recovery()
    assert not watchdog.can_recover()


def test_runner_does_not_treat_please_wait_as_controller_disconnect():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    snapshot = SimpleNamespace(
        smart_state="controller_disconnected",
        smart_confidence=0.90,
        v3=fake_v3("modal_warning", selected_item="请稍候", confidence=0.86),
    )
    decision = V4Mode3Runner._decide(runner, snapshot, RouteContext())
    assert decision.button == ""
    assert decision.name == "wait_modal_loading"


def test_runner_ignores_smart_prestart_when_v3_sees_buy_flow_page():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    snapshot = SimpleNamespace(
        smart_state="prestart",
        smart_confidence=0.95,
        v3=fake_v3("vehicle_mastery", active_tab="车辆", selected_item="XP", confidence=0.94),
    )

    decision = V4Mode3Runner._decide(runner, snapshot, RouteContext())
    assert decision.name == "back_out_from_buy_flow"
    assert not decision.terminal
    assert not V4Mode3Runner._buy_phase_can_handoff_to_v4(runner, snapshot)


def test_runner_allows_smart_prestart_only_when_v3_is_ambiguous_or_race_menu():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    snapshot = SimpleNamespace(
        smart_state="prestart",
        smart_confidence=0.95,
        v3=fake_v3("unknown", selected_item="", confidence=0.0),
    )

    decision = V4Mode3Runner._decide(runner, snapshot, RouteContext())
    assert decision.name == "arrived_race_menu"
    assert decision.terminal
    assert V4Mode3Runner._buy_phase_can_handoff_to_v4(runner, snapshot)

    start_event_menu = SimpleNamespace(
        smart_state="prestart",
        smart_confidence=0.99,
        v3=fake_v3("pause_story", selected_item="开始竞赛赛事", confidence=0.97),
    )
    decision = V4Mode3Runner._decide(runner, start_event_menu, RouteContext())
    assert decision.name == "arrived_race_menu"
    assert decision.terminal


def test_decide_opens_pause_when_v1_says_racing_but_v3_not_race_hud():
    # Regression (2026-05-30): after buying, the back-out (B B B) landed in free
    # roam at the festival start line. V3 read it as `unknown` while V1 smart
    # mis-read it as RACING, so navigation falsely "arrived at race_hud" and handed
    # off to the farm -- the car was left idling in free roam ("买完车后不会自动刷图").
    # Now V1 smart=RACING WITHOUT a real V3 race_hud must NOT confirm arrival;
    # instead open the pause menu (Menu) and keep navigating to EventLab.
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    for screen in ("unknown", "free_roam_hud", "idle_showcase"):
        snap = SimpleNamespace(
            v3=fake_v3(screen, selected_item="", confidence=0.4),
            smart_state="racing",
            smart_confidence=0.9,
        )
        assert not V4Mode3Runner._smart_state_confirms_eventlab(runner, snap), screen
        d = V4Mode3Runner._decide(runner, snap, RouteContext())
        assert d.name == "open_pause_from_world", screen
        assert normalize_button(d.button) == "start" and not d.terminal
    # A REAL V3 race_hud + smart=RACING still confirms we are genuinely racing.
    racing = SimpleNamespace(
        v3=fake_v3("race_hud", selected_item=""), smart_state="racing", smart_confidence=0.9
    )
    assert V4Mode3Runner._smart_state_confirms_eventlab(runner, racing)
    d2 = V4Mode3Runner._decide(runner, racing, RouteContext())
    assert d2.name == "arrived_race_hud" and d2.terminal


def test_farm_phase_watchdog_stops_stuck_smart_runner():
    class FakeSmartRunner:
        def __init__(self):
            self.exit_reason = None
            self.stop_called = False
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs

        def is_running(self):
            return not self.stop_called

        def stop(self):
            self.stop_called = True
            self.exit_reason = "manual_stop"

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.smart_runner = FakeSmartRunner()
    runner._farm_mode = "smart"
    runner.watchdog_seconds = 0.01
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[])
    runner._log = lambda message: None
    runner._sleep = lambda _seconds: (time.sleep(0.002) or True)

    assert V4Mode3Runner._run_farm_phase(runner, 0.001, auto_focus=False, require_foreground=True)
    assert runner.smart_runner.stop_called
    assert runner.smart_runner.started_with["total_seconds"] == 0.001
    assert any("farm_watchdog_stop" in item for item in runner.report.errors)


def test_farm_phase_zero_duration_means_unlimited_until_runner_exits():
    class FakeVisionFarmRunner:
        def __init__(self):
            self.exit_reason = "graceful_exit"
            self.stop_called = False
            self._thread = None
            self.polls = 0

        def start(self, **kwargs):
            self.started_with = kwargs

        def is_running(self):
            self.polls += 1
            return self.polls <= 2

        def stop(self):
            self.stop_called = True

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.vision_farm_runner = FakeVisionFarmRunner()
    runner._farm_mode = "vision"
    runner.watchdog_seconds = 0.01
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[])
    logs = []
    runner._log = logs.append
    runner._sleep = lambda _seconds: True

    assert V4Mode3Runner._run_farm_phase(runner, None, auto_focus=False, require_foreground=True)
    assert runner.vision_farm_runner.started_with["total_seconds"] is None
    assert not runner.vision_farm_runner.stop_called
    assert not runner.report.errors
    assert any("持续跑模式一" in message for message in logs)


def test_farm_seconds_zero_is_unlimited_but_missing_override_uses_default():
    assert V4Mode3Runner._farm_seconds(0.0) is None
    assert V4Mode3Runner._farm_seconds(-1.0) is None
    assert V4Mode3Runner._farm_seconds(12.5) == 12.5
    assert V4Mode3Runner._farm_seconds(None) > 0


def test_loop_rounds_zero_means_unlimited_and_default_is_single_round():
    assert V4Mode3Runner._loop_rounds(None) == 1
    assert V4Mode3Runner._loop_rounds(1) == 1
    assert V4Mode3Runner._loop_rounds(2) == 2
    assert V4Mode3Runner._loop_rounds(0) is None
    assert V4Mode3Runner._loop_rounds(-3) is None


def test_run_loop_repeats_full_mode_three_rounds_and_only_delays_first_round():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner._stop = threading.Event()
    runner._log = lambda _message: None
    runner._sleep = lambda _seconds: True
    runner._farm_seconds = lambda _seconds: 180.0
    runner.report = SimpleNamespace(stopped_reason="completed")
    calls = []

    def fake_run_once(**kwargs):
        calls.append(kwargs)
        runner.report.stopped_reason = "completed"
        return True

    runner.run_once = fake_run_once

    assert V4Mode3Runner.run_loop(
        runner,
        startup_delay=4.0,
        farm_seconds=180.0,
        run_buy=True,
        run_farm=True,
        exit_after_farm=True,
        auto_focus=True,
        require_foreground=True,
        loop_rounds=2,
    )
    assert len(calls) == 2
    assert calls[0]["startup_delay"] == 4.0
    assert calls[1]["startup_delay"] == 0.0
    assert all(call["run_buy"] is True for call in calls)
    assert all(call["run_farm"] is True for call in calls)


def test_exit_after_farm_keeps_verifying_after_idle_menu_press():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner._log = lambda message: None
    runner._sleep = lambda _seconds: True
    runner._ensure_foreground = lambda *args, **kwargs: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    snapshots = iter(
        [
            SimpleNamespace(v3=fake_v3("post_race_next", selected_item="HIDE"), smart_state="", smart_confidence=0.0),
            SimpleNamespace(v3=fake_v3("idle_showcase", selected_item=""), smart_state="", smart_confidence=0.0),
            SimpleNamespace(v3=fake_v3("pause_story", active_tab="剧情", selected_item="开始竞赛赛事"), smart_state="", smart_confidence=0.0),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._exit_after_farm(runner, SimpleNamespace(), False, True)
    assert taps == ["b", "start"]


def test_exit_after_farm_accepts_race_menu_as_safe_handoff():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner._log = lambda message: None
    runner._sleep = lambda _seconds: True
    runner._ensure_foreground = lambda *args, **kwargs: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    runner._recognize = lambda: SimpleNamespace(
        v3=fake_v3("race_menu", selected_item="开始竞赛赛事"),
        smart_state="",
        smart_confidence=0.0,
    )

    assert V4Mode3Runner._exit_after_farm(runner, SimpleNamespace(), False, True)
    assert taps == []


def test_buy_phase_watchdog_stops_stuck_buy_runner():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.stop_called = False
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs

        def is_running(self):
            return not self.stop_called

        def stop(self):
            self.stop_called = True

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 0.01
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: (time.sleep(0.002) or True)
    runner._record_step = lambda *args, **kwargs: None
    runner._write_attention_report = lambda *args, **kwargs: "attention.json"
    runner._recognize = lambda: SimpleNamespace(
        v3=fake_v3("vehicle_buy_grid", selected_item="WRX STI"),
        smart_state="",
        smart_confidence=0.0,
        elapsed_ms=1.0,
    )

    assert not V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.stop_called
    assert runner.buy_runner.started_with["total_seconds"] is None
    assert any("buy_phase_watchdog_stop" in item for item in runner.report.errors)


def test_buy_phase_world_map_recovery_closes_map_and_restarts():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs
            self.start_count += 1
            self.running = True

        def is_running(self):
            if self.start_count >= 2:
                self.stop_reason = "points_exhausted"
                return False
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

        def _invalidate_ocr(self):
            pass

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 0.01
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._pad_provider = lambda: SimpleNamespace(tap=lambda *args, **kwargs: None)
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: (time.sleep(0.002) or True)
    runner._record_step = lambda *args, **kwargs: None
    runner._write_attention_report = lambda *args, **kwargs: "attention.json"
    taps = []
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    runner._recognize = lambda: SimpleNamespace(
        v3=fake_v3("world_map"),
        smart_state="",
        smart_confidence=0.0,
        elapsed_ms=1.0,
    )

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.start_count == 2
    assert runner.buy_runner.stop_count == 1
    assert taps == ["b"]


def test_buy_phase_preflight_skips_buy_runner_when_already_on_eventlab_route():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs
            self.start_count += 1
            self.running = True

        def is_running(self):
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    runner._recognize = lambda: SimpleNamespace(
        v3=fake_v3("eventlab_home", selected_item="车库布局"),
        smart_state="",
        smart_confidence=0.0,
        elapsed_ms=1.0,
    )

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.start_count == 0
    assert runner.buy_runner.stop_count == 0


def test_buy_phase_preflight_backs_out_of_autoshow_child_before_starting_buy_runner():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.start_count += 1
            self.stop_reason = "points_exhausted"
            self.running = False

        def is_running(self):
            return self.running

        def stop(self):
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._pad_provider = lambda: SimpleNamespace()
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("autoshow_buy_sell", active_tab="角色", selected_item="自定义角色"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("pause_story", active_tab="剧情", selected_item="世界地图"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert taps == ["b"]
    assert runner.buy_runner.start_count == 1


def test_buy_phase_preflight_dismisses_controller_before_smart_handoff():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.start_count += 1
            self.running = True

        def is_running(self):
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._pad_provider = lambda: SimpleNamespace()
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("controller_disconnected", selected_item="controller"),
                smart_state="controller_disconnected",
                smart_confidence=0.99,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("race_pause_menu", selected_item="return to race"),
                smart_state="",
                smart_confidence=0.90,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert taps == ["a"]
    assert runner.buy_runner.start_count == 0
    assert runner.buy_runner.stop_count == 0


def test_buy_phase_preflight_hands_restart_modal_to_v4_navigation():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.start_count += 1
            self.running = True

        def is_running(self):
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    runner._recognize = lambda: SimpleNamespace(
        v3=fake_v3("modal_warning", selected_item="重新开始赛事"),
        smart_state="confirm_restart",
        smart_confidence=0.99,
        elapsed_ms=1.0,
    )

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.start_count == 0
    assert runner.buy_runner.stop_count == 0


def test_buy_phase_preflight_opens_pause_for_driving_state_then_starts_buy_runner():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.start_count += 1
            self.stop_reason = "points_exhausted"
            self.running = False

        def is_running(self):
            return self.running

        def stop(self):
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._pad_provider = lambda: SimpleNamespace()
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("unknown", selected_item=""),
                smart_state="racing",
                smart_confidence=0.91,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("pause_story", active_tab="story", selected_item="world map"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert taps == ["start"]
    assert runner.buy_runner.start_count == 1


def test_buy_phase_preflight_driving_state_hands_off_when_pause_is_race_pause():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.start_count += 1
            self.running = True

        def is_running(self):
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._pad_provider = lambda: SimpleNamespace()
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("unknown", selected_item=""),
                smart_state="racing",
                smart_confidence=0.91,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("race_pause_menu", active_tab="race pause", selected_item="return to race"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert taps == ["start"]
    assert runner.buy_runner.start_count == 0
    assert runner.buy_runner.stop_count == 0


def test_buy_phase_monitor_hands_off_after_buy_runner_started():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs
            self.start_count += 1
            self.running = True

        def is_running(self):
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    # The buy monitor now DEBOUNCES the handoff: it needs TWO consecutive checks on
    # an EventLab/race page before aborting the buy (a single car-grid frame can
    # mis-read as eventlab_my_cars). Call 1 is the preflight (a buy grid); every
    # later call returns the EventLab page, so the monitor confirms on its 2nd tick.
    buy_grid = SimpleNamespace(
        v3=fake_v3("vehicle_buy_grid", selected_item="WRX STI"),
        smart_state="",
        smart_confidence=0.0,
        elapsed_ms=1.0,
    )
    eventlab = SimpleNamespace(
        v3=fake_v3("eventlab_home", selected_item="eventlab"),
        smart_state="",
        smart_confidence=0.0,
        elapsed_ms=1.0,
    )
    state = {"calls": 0}

    def fake_recognize(*args, **kwargs):
        state["calls"] += 1
        return buy_grid if state["calls"] == 1 else eventlab

    runner._recognize = fake_recognize

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.start_count == 1
    assert runner.buy_runner.stop_count == 1
    assert state["calls"] >= 3  # preflight + >=2 monitor checks (debounce)


def test_buy_phase_monitor_keeps_buy_runner_on_buy_pages_even_if_smart_false_prestart():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self.running_checks = 0
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs
            self.start_count += 1
            self.running = True

        def is_running(self):
            if not self.running:
                return False
            self.running_checks += 1
            if self.running_checks == 1:
                return True
            self.stop_reason = "points_exhausted"
            self.running = False
            return False

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("vehicle_buy_grid", selected_item="WRX STI"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("vehicle_buy_grid", selected_item="IMPREZA 22B-STI VERSION"),
                smart_state="prestart",
                smart_confidence=0.92,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.start_count == 1
    assert runner.buy_runner.stop_count == 0


def test_navigate_dispatches_to_v5_when_nav_mode_is_v5():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    calls = []
    runner._navigate_via_v5 = lambda pad, a, r: (calls.append("v5") or True)
    runner._navigate_to_eventlab_prestart = lambda pad, a, r: (calls.append("v4") or True)
    runner.nav_mode = "v5"
    assert V4Mode3Runner._navigate(runner, None, False, True) is True
    runner.nav_mode = "v4"
    V4Mode3Runner._navigate(runner, None, False, True)
    assert calls == ["v5", "v4"]
