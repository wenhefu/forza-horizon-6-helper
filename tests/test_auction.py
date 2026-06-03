"""Tests for the Phase C auction-house screen detectors (OCR strings captured live).

The CONFIRM/BID/DETAIL/NETWORK constants are the real zh-Hans strings from the captured
buy-out flow (search -> results list -> 车辆详情 -> 买断/竞价 confirm)."""
from v3.buying_ui import (
    detect_auction_detail,
    detect_auction_house,
    detect_auction_results,
    detect_auction_search,
    detect_bid_confirm,
    detect_buyout_confirm,
    detect_network_warning,
)

HOUSE = "拍卖场 | 搜索拍卖 | 开始拍卖 | 我的竞价 | 我的拍卖 | 拍卖提醒 | 选择 | 返回"
SEARCH = "搜寻 | 车厂 | 任意 | 型号 | 任意 | 性能等级 | 车辆类型 | 最高竞价 | 任意 | 最高买断价 | 确认 | 返回"
RESULTS = "拍卖场 | 拍卖详情 | 即将结束 | 选择 | 返回 | 拍卖选项 | RT 拍卖提醒 | REVUELTO | 41,000 | 183,000"
# SS3: 车辆详情 (single-listing detail) -- car stats + 竞价(focused)/买断 action rows.
DETAIL = "拍卖详情 | 车辆详情 | PORTOFINO '18 | 2018 法拉利 | 史诗 | S1 714 | 传动系统 后轮驱动 | 马力 441 千瓦 | 扭矩 760 牛米 | 车重 1664 千克 | 3 分钟 | 竞价 36,000 | 买断 240,000"
# SS5: 买断 confirm (the only dialog the snipe may confirm).
BUYOUT_CONFIRM = "买断 | 是否确定要买断该拍卖？ | 嗯 | 不"
# SS4: 竞价 (BID) confirm -- the danger dialog.
BID_CONFIRM = "竞价 | 是否确定要为该拍卖竞价 CR 36,000？ | 如果有人出价高于您，您可以立即从“我的竞价”取回点数。 | 嗯 | 不"
# SS2: online-disconnect banner over the results.
NETWORK = "注意！ | 连接已断开，请稍后再试 | 返回漫游模式才可接受邀请 | 拍卖详情 | 240,000"


def test_auction_search_detected():
    m = detect_auction_search(SEARCH)
    assert m["visible"] and m["has_buyout_cap"]
    assert not detect_auction_search(HOUSE)["visible"]


def test_auction_results_detected():
    m = detect_auction_results(RESULTS)
    assert m["visible"] and m["has_options"]
    assert not detect_auction_results(HOUSE)["visible"]
    # the single-listing detail also carries '拍卖详情' but must NOT read as the list
    assert not detect_auction_results(DETAIL)["visible"]


def test_auction_detail_detected():
    m = detect_auction_detail(DETAIL)
    assert m["visible"] and m["has_buyout"] and m["has_bid"]
    # the results list (no car stats / no 车辆详情 pager) is not the detail screen
    assert not detect_auction_detail(RESULTS)["visible"]
    # the search screen has 最高买断价/最高竞价 but no car stats -> not detail
    assert not detect_auction_detail(SEARCH)["visible"]


def test_auction_house_detected_and_disambiguated():
    assert detect_auction_house(HOUSE)["visible"]
    # the header '拍卖场' also appears on results/search -> those must NOT read as the house
    assert not detect_auction_house(RESULTS)["visible"]
    assert not detect_auction_house(SEARCH)["visible"]


def test_buyout_confirm_shape():
    assert detect_buyout_confirm(BUYOUT_CONFIRM)["visible"]
    assert not detect_buyout_confirm("拍卖详情 | 即将结束")["visible"]
    # CRITICAL: the search screen (最高买断价 + 确认) must NOT read as a buy-out confirm
    assert not detect_buyout_confirm(SEARCH)["visible"]
    # CRITICAL: the BID confirm must NOT read as a buy-out confirm
    assert not detect_buyout_confirm(BID_CONFIRM)["visible"]


def test_bid_confirm_shape_and_disambiguation():
    assert detect_bid_confirm(BID_CONFIRM)["visible"]
    # the buy-out confirm and the detail/results screens are NOT the bid dialog
    assert not detect_bid_confirm(BUYOUT_CONFIRM)["visible"]
    assert not detect_bid_confirm(DETAIL)["visible"]
    assert not detect_bid_confirm(RESULTS)["visible"]


def test_network_warning_detected():
    assert detect_network_warning(NETWORK)["visible"]
    assert not detect_network_warning(RESULTS)["visible"]
    assert not detect_network_warning(DETAIL)["visible"]


def test_none_detected_on_blank_or_unrelated():
    for ocr in ("", "我的车辆 | 斯巴鲁 | 传奇"):
        assert not detect_auction_search(ocr)["visible"]
        assert not detect_auction_results(ocr)["visible"]
        assert not detect_auction_detail(ocr)["visible"]
        assert not detect_auction_house(ocr)["visible"]
        assert not detect_buyout_confirm(ocr)["visible"]
        assert not detect_bid_confirm(ocr)["visible"]
        assert not detect_network_warning(ocr)["visible"]
