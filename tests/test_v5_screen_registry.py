"""Pure-logic tests for the V5 screen registry + generic navigator (no game)."""
from types import SimpleNamespace

import pytest

from v3.ui_tree import SCREEN_TO_NODE, UI_NODES
from v4.decision import normalize_button
from v5.screen_registry import (
    REGISTRY,
    NextAction,
    NoRouteError,
    next_button,
    plan_route,
)


def fake_u(screen, selected_item="", ocr_regions=None):
    return SimpleNamespace(
        screen=screen,
        selected_item=selected_item,
        ocr_regions=[SimpleNamespace(text=t) for t in (ocr_regions or [])],
    )


def test_registry_built_from_ui_tree_covers_all_screens():
    # Built by iterating ui_tree -> every recognized screen has a spec, no dup list.
    for screen, node_id in SCREEN_TO_NODE.items():
        spec = REGISTRY.get(screen)
        assert spec is not None, screen
        assert spec.node_id == node_id
        assert spec.title == UI_NODES[node_id].title
        assert spec.ui_node is UI_NODES[node_id]


def test_child_and_parent_edges_synthesized():
    edges = REGISTRY.neighbors("vehicle_buy_grid")
    parents = [t for t in edges if t.kind == "parent"]
    assert parents and parents[0].button == "B" and parents[0].target == "autoshow_showroom"
    # child edge to manufacturer_grid uses the raw slash button "Back/View"
    to_mfr = [t for t in edges if t.target == "manufacturer_grid"]
    assert to_mfr and to_mfr[0].button == "Back/View"
    assert normalize_button("Back/View") == "back"


def test_plan_route_simple_child_chain():
    assert plan_route("eventlab_home", "eventlab_events") == ["A"]
    assert plan_route("eventlab_events", "eventlab_race_type") == ["A"]
    assert plan_route("eventlab_events", "race_menu") == ["A", "A", "A"]


def test_plan_route_multi_hop_from_free_roam():
    route = plan_route("free_roam_hud", "eventlab_events")
    assert route, "free roam should reach the EventLab list"
    assert normalize_button(route[0]) == "start"  # opens the pause menu first
    # crosses a tab hop (RB) to reach the creative-hub branch
    assert any(normalize_button(b) == "rb" for b in route)


def test_plan_route_back_to_parent_uses_b():
    assert plan_route("race_menu", "eventlab_my_cars") == ["B"]
    assert plan_route("race_hud", "eventlab_my_cars") == ["B", "B"]


def test_plan_route_unreachable_raises():
    # external_overlay has no parent and nothing targets it -> unreachable sink.
    with pytest.raises(NoRouteError):
        plan_route("race_menu", "external_overlay")


def test_next_button_arrived_at_goal():
    act = next_button(fake_u("race_menu"), goal="race_menu")
    assert act.name == "arrived" and normalize_button(act.button) == ""


def test_next_button_routes_one_step():
    act = next_button(fake_u("eventlab_home"), goal="eventlab_events")
    assert act.name == "route_step" and normalize_button(act.button) == "a"


def test_empty_events_recovery_fires_via_ocr_and_focus():
    # The user-reported network-glitch case: eventlab_events screen but the list
    # OCRs "找不到赛事". Recovery (wait, no blind button) must fire.
    via_ocr = next_button(fake_u("eventlab_events", ocr_regions=["找不到赛事"]), goal="race_menu")
    assert via_ocr.recovery and via_ocr.name == "recovery:eventlab_empty_events_network_glitch"
    assert normalize_button(via_ocr.button) == ""  # wait, do not blind-press
    via_focus = next_button(fake_u("eventlab_events", selected_item="找不到赛事"), goal="race_menu")
    assert via_focus.recovery


def test_empty_events_recovery_does_not_fire_on_normal_list():
    act = next_button(fake_u("eventlab_events", selected_item="ANYTHING GOES"), goal="race_menu")
    # The empty-events recovery must NOT fire on a populated list...
    assert not act.recovery
    # ...and since the focus isn't the target event yet, the navigator SCANS for it
    # (focus guard) rather than blind-pressing A on the wrong card.
    assert act.name.startswith("scan_for")


def test_recovery_takes_precedence_over_routing():
    # A route exists (eventlab_events -> race_menu), but the empty-events recovery
    # must win so we don't blindly press A into "找不到赛事".
    act = next_button(fake_u("eventlab_events", ocr_regions=["找不到赛事"]), goal="race_menu")
    assert act.recovery is True


def test_button_normalization_in_sync_with_v4():
    # Buttons authored in ui_tree (and surfaced in routes) normalize as expected.
    assert normalize_button("A/Enter") == "a"
    assert normalize_button("Back/View") == "back"
    assert normalize_button("X/A") == "x"
    assert normalize_button("B/Esc") == "b"
    assert normalize_button("Menu") == "start"
    assert normalize_button("") == ""


def test_focus_guard_scans_grid_instead_of_blind_a():
    # eventlab_my_cars -> race_menu first step is A on "22B". If the focus is NOT
    # 22B, scan (dpad_right) -- never blind-press A on the wrong car.
    mism = next_button(fake_u("eventlab_my_cars", selected_item="BRZ"), goal="race_menu")
    assert mism.name == "scan_for:22B" and normalize_button(mism.button) == "dpad_right"
    matched = next_button(
        fake_u("eventlab_my_cars", selected_item="IMPREZA 22B-STI VERSION"), goal="race_menu"
    )
    assert matched.name == "route_step" and normalize_button(matched.button) == "a"


def test_focus_guard_event_card_requires_target_event():
    mism = next_button(fake_u("eventlab_events", selected_item="机甲爽翻天"), goal="race_menu")
    assert mism.name.startswith("scan_for") and normalize_button(mism.button) == "dpad_right"
    matched = next_button(fake_u("eventlab_events", selected_item="SP FARM 10"), goal="race_menu")
    assert matched.name == "route_step" and normalize_button(matched.button) == "a"


def test_focus_guard_manufacturer_requires_subaru():
    mism = next_button(fake_u("manufacturer_grid", selected_item="HONDA"), goal="vehicle_buy_grid")
    assert mism.name == "scan_for:品牌" and normalize_button(mism.button) == "dpad_down"
    matched = next_button(
        fake_u("manufacturer_grid", selected_item="SUBARU 斯巴鲁"), goal="vehicle_buy_grid"
    )
    assert matched.name == "route_step" and normalize_button(matched.button) == "a"


def test_non_a_edges_are_not_focus_guarded():
    # vehicle_buy_grid -> manufacturer_grid is "Back/View" (not A) -> fires freely.
    act = next_button(fake_u("vehicle_buy_grid", selected_item="anything"), goal="manufacturer_grid")
    assert act.name == "route_step" and normalize_button(act.button) == "back"
