"""Tests for the sell-duplicates planner + the 选择操作 action-menu detector."""
from v3.buying_ui import detect_remove_confirm, detect_vehicle_action_menu
from v4.sell_planner import VehicleCard, plan_duplicate_sales, summarize_plan
from v4.sell_runner import distinct_models


def test_remove_confirm_dialog_detected():
    ocr = "从车库移除车辆 | 确定要移除所选车辆吗？ | 不 | 嗯"
    assert detect_remove_confirm(ocr)["visible"] is True


def test_remove_confirm_not_detected_on_action_menu_or_blank():
    # the action menu is NOT the confirm dialog -> must not be mistaken for it
    assert detect_remove_confirm("选择操作 | 上车 | 从车库移除车辆 | 取消")["visible"] is False
    assert detect_remove_confirm("")["visible"] is False


def test_distinct_models_dedupes_preserving_order():
    # dup copies share names; the reliable signal is the distinct SET of models
    assert distinct_models(["22B", "M5", "22B", "22B", "WRANGLER", "M5"]) == ["22B", "M5", "WRANGLER"]
    assert distinct_models(["", "  ", "X", None]) == ["X"]
    assert distinct_models([]) == []


def test_sell_runner_stop_event():
    # the GUI's 停止 sets this event; run_sell's loop checks `not self._stopped()`
    import threading

    from v4.sell_runner import SellDuplicatesRunner

    e = threading.Event()
    r = SellDuplicatesRunner(object(), object(), stop_event=e)
    assert r._stopped() is False
    e.set()
    assert r._stopped() is True
    assert SellDuplicatesRunner(object(), object())._stopped() is False  # no event -> never stopped


# --- detect_vehicle_action_menu ------------------------------------------------

def test_action_menu_detected_from_auction_path_ocr():
    ocr = "选择操作 | 拍卖车辆 | 上车 | 添加至收藏 | 查看车辆 | 查看历史记录 | 从车库移除车辆 | 选择 | 取消"
    m = detect_vehicle_action_menu(ocr)
    assert m["visible"] and m["has_auction"] and m["has_remove"]
    assert m["has_favorite"] and m["has_drive"]
    assert m["favorited"] is False  # 添加至收藏 -> not favorited


def test_action_menu_my_vehicles_path_is_remove_only_not_favorited():
    # via 我的车辆 directly: no 拍卖车辆, has 从车库移除车辆, 添加至收藏 => sellable
    ocr = "选择操作 | 上车 | 添加至收藏 | 查看车辆 | 查看历史记录 | 从车库移除车辆 | 举报并移除涂装 | 选择 | 取消"
    m = detect_vehicle_action_menu(ocr)
    assert m["visible"] and m["has_remove"] and not m["has_auction"]
    assert m["favorited"] is False
    assert m["sellable"] is True          # removable + not favorited


def test_action_menu_favorited_car_is_protected():
    # a favorited car shows 从收藏中移除 -> favorited=True -> never sell
    ocr = "选择操作 | 上车 | 从收藏中移除 | 查看车辆 | 从车库移除车辆 | 选择 | 取消"
    m = detect_vehicle_action_menu(ocr)
    assert m["visible"] and m["favorited"] is True
    assert m["sellable"] is False


def test_action_menu_my_favorites_variant_is_detected():
    # the live driving/favorited car shows '从我的收藏中移除' (note the 我的) -> must still
    # read favorited=True, else we would fail to protect the farm car.
    ocr = "选择操作 | 从我的收藏中移除 | 查看车辆 | 查看历史记录 | 举报并移除涂装 | 选择 | 取消"
    m = detect_vehicle_action_menu(ocr)
    assert m["favorited"] is True
    assert m["sellable"] is False


def test_action_menu_driving_car_has_no_remove_option():
    # GAME-NATIVE protection: the currently-driving car's menu has no 上车 and no
    # 从车库移除车辆 -> the game refuses removal -> never sellable.
    ocr = "选择操作 | 从我的收藏中移除 | 查看车辆 | 查看历史记录 | 举报并移除涂装 | 选择 | 取消"
    m = detect_vehicle_action_menu(ocr)
    assert m["has_remove"] is False and m["is_driving"] is True
    assert m["sellable"] is False


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
