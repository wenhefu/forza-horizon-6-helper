"""Tests for v3.buying_ui.detect_skill_points -- reads available mastery points.

OCR strings are the real ones captured live from FH6 (zh-Hans).
"""
from v3.buying_ui import detect_skill_points


def test_reads_count_from_vehicles_tab_tile():
    # '18技术点数可用' on the 车辆 tab 车辆熟练度 tile (number before 技术点数)
    ocr = "913 | 201 | 1998斯巴鲁 | 已拥有648辆车 | 车辆熟练度 | 18技术点数可用 | 调校车辆"
    assert detect_skill_points(ocr) == 18


def test_reads_count_from_mastery_tree_footer():
    # mastery tree footer: '可用点数' then '18 (' as a separate OCR token
    ocr = "车辆熟练度 | IMPREZA 22B-STIVERSION | 已拥有 | 可用点数 | 18 ( | 返回"
    assert detect_skill_points(ocr) == 18


def test_reads_zero_points():
    assert detect_skill_points("可用点数 | 0 | 返回") == 0
    assert detect_skill_points("0技术点数可用") == 0


def test_insufficient_popup_has_no_number_returns_none():
    # the '技术点数不足' popup carries no count -> None (handled by skill_points_exhausted)
    assert detect_skill_points("技术点数不足 | 确定") is None


def test_returns_none_when_absent_or_empty():
    assert detect_skill_points("") is None
    assert detect_skill_points(None) is None
    assert detect_skill_points("拍卖场 | 搜索拍卖 | 开始拍卖") is None


def test_mastery_footer_takes_precedence_over_stray_numbers():
    # a stray '技术点数不足' must not shadow the real '可用点数 7'
    ocr = "可用点数 | 7 | 节点 | 技术点数不足提示历史"
    assert detect_skill_points(ocr) == 7


def test_various_counts():
    assert detect_skill_points("123技术点数可用") == 123
    assert detect_skill_points("可用点数 5") == 5
