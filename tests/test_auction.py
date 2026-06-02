"""Tests for the Phase C auction-house screen detectors (OCR strings captured live)."""
from v3.buying_ui import (
    detect_auction_house,
    detect_auction_results,
    detect_auction_search,
    detect_buyout_confirm,
)

HOUSE = "拍卖场 | 搜索拍卖 | 开始拍卖 | 我的竞价 | 我的拍卖 | 拍卖提醒 | 选择 | 返回"
SEARCH = "搜寻 | 车厂 | 任意 | 型号 | 任意 | 性能等级 | 车辆类型 | 最高竞价 | 任意 | 最高买断价 | 确认 | 返回"
RESULTS = "拍卖场 | 拍卖详情 | 即将结束 | 选择 | 返回 | 拍卖选项 | RT 拍卖提醒 | REVUELTO | 41,000 | 183,000"


def test_auction_search_detected():
    m = detect_auction_search(SEARCH)
    assert m["visible"] and m["has_buyout_cap"]
    assert not detect_auction_search(HOUSE)["visible"]


def test_auction_results_detected():
    m = detect_auction_results(RESULTS)
    assert m["visible"] and m["has_options"]
    assert not detect_auction_results(HOUSE)["visible"]


def test_auction_house_detected_and_disambiguated():
    assert detect_auction_house(HOUSE)["visible"]
    # the header '拍卖场' also appears on results/search -> those must NOT read as the house
    assert not detect_auction_house(RESULTS)["visible"]
    assert not detect_auction_house(SEARCH)["visible"]


def test_none_detected_on_blank_or_unrelated():
    for ocr in ("", "我的车辆 | 斯巴鲁 | 传奇"):
        assert not detect_auction_search(ocr)["visible"]
        assert not detect_auction_results(ocr)["visible"]
        assert not detect_auction_house(ocr)["visible"]


def test_buyout_confirm_shape():
    assert detect_buyout_confirm("买断 | 确定要买断吗？ | 是 | 否")["visible"]
    assert not detect_buyout_confirm("拍卖详情 | 即将结束")["visible"]
