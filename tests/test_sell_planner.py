"""Tests for the sell-duplicates planner + the 选择操作 action-menu detector."""
from v3.buying_ui import detect_vehicle_action_menu
from v4.sell_planner import VehicleCard, plan_duplicate_sales, summarize_plan
from v4.sell_runner import distinct_models


def test_distinct_models_dedupes_preserving_order():
    # dup copies share names; the reliable signal is the distinct SET of models
    assert distinct_models(["22B", "M5", "22B", "22B", "WRANGLER", "M5"]) == ["22B", "M5", "WRANGLER"]
    assert distinct_models(["", "  ", "X", None]) == ["X"]
    assert distinct_models([]) == []


# --- detect_vehicle_action_menu ------------------------------------------------

def test_action_menu_detected_from_live_ocr():
    ocr = "选择操作 | 拍卖车辆 | 上车 | 添加至收藏 | 查看车辆 | 查看历史记录 | 从车库移除车辆 | 选择 | 取消"
    m = detect_vehicle_action_menu(ocr)
    assert m["visible"] and m["has_auction"] and m["has_remove"]
    assert m["has_favorite"] and m["has_drive"]


def test_action_menu_not_detected_elsewhere():
    assert not detect_vehicle_action_menu("拍卖场 | 搜索拍卖 | 开始拍卖")["visible"]
    assert not detect_vehicle_action_menu("")["visible"]


# --- plan_duplicate_sales (safety) ---------------------------------------------

def _c(name, current=False, fav=False, cid=""):
    return VehicleCard(name=name, is_current=current, is_favorite=fav, card_id=cid)


def test_single_copy_is_never_sold():
    assert plan_duplicate_sales([_c("22B"), _c("BRZ")]) == []


def test_three_dupes_keep_one_sell_two():
    cards = [_c("22B", cid="a"), _c("22B", cid="b"), _c("22B", cid="c")]
    sell = plan_duplicate_sales(cards, keep_per_model=1)
    assert len(sell) == 2  # keep exactly one


def test_favorite_is_kept_and_never_sold():
    cards = [_c("22B", fav=True, cid="fav"), _c("22B", cid="b"), _c("22B", cid="c")]
    sell = plan_duplicate_sales(cards, keep_per_model=1)
    assert {c.card_id for c in sell} == {"b", "c"}
    assert all(not c.is_favorite for c in sell)


def test_current_car_is_kept_and_never_sold():
    cards = [_c("22B", current=True, cid="cur"), _c("22B", cid="b"), _c("22B", cid="c")]
    sell = plan_duplicate_sales(cards, keep_per_model=1)
    assert {c.card_id for c in sell} == {"b", "c"}
    assert all(not c.is_current for c in sell)


def test_protected_copies_never_sold_even_beyond_keep():
    # 1 current + 1 favorite + 3 plain -> never sell the 2 protected, keep>=1 -> sell 3 plain
    cards = [
        _c("22B", current=True, cid="cur"), _c("22B", fav=True, cid="fav"),
        _c("22B", cid="p1"), _c("22B", cid="p2"), _c("22B", cid="p3"),
    ]
    sell = plan_duplicate_sales(cards, keep_per_model=1)
    assert {c.card_id for c in sell} == {"p1", "p2", "p3"}


def test_keep_per_model_two():
    cards = [_c("22B", cid="a"), _c("22B", cid="b"), _c("22B", cid="c")]
    assert len(plan_duplicate_sales(cards, keep_per_model=2)) == 1


def test_distinct_models_not_treated_as_dupes():
    cards = [_c("22B"), _c("BRZ"), _c("SUPRA")]
    assert plan_duplicate_sales(cards) == []


def test_summary_reports_per_model():
    cards = [_c("22B", fav=True), _c("22B"), _c("22B"), _c("BRZ")]
    s = summarize_plan(cards, keep_per_model=1)
    assert s["total_cards"] == 4 and s["total_to_sell"] == 2
    assert s["by_model"]["22B"]["owned"] == 3 and s["by_model"]["22B"]["sell"] == 2
    assert "BRZ" not in s["by_model"]
