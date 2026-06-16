"""Unit tests for the un-owned car SURVEY (v4/unowned_surveyor.py).

Pure-logic only -- no game. Detection functions run on synthetic frames built to the validated
16:9 geometry; the traversal runs against a FakeGridIO that models a scrolling collection grid.
"""
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from v4.unowned_surveyor import (
    Cell,
    GridView,
    UnownedSurveyor,
    classify_obtain,
    cell_image_box,
    focused_cell,
    format_report,
    is_placeholder_cell,
    read_cell_name,
    COL_CENTERS,
    ROW_CENTERS,
    NAME_DY,
    METHOD_AUTOSHOW,
    METHOD_WHEELSPIN,
    METHOD_REWARD,
    OBTAIN_BUY,
    OBTAIN_REWARD,
    OBTAIN_UNKNOWN,
)


# ----------------------------------------------------------------------------- classify_obtain
def test_classify_buy_autoshow_only():
    kind, methods = classify_obtain("此车可通过以下途径获得：车展。是否要从车展购买这辆车?")
    assert kind == OBTAIN_BUY
    assert methods == [METHOD_AUTOSHOW]


def test_classify_buy_wheelspin_and_autoshow():
    kind, methods = classify_obtain("此车可通过以下途径获得：抽奖,车展。是否要从车展购买这辆车?")
    assert kind == OBTAIN_BUY
    assert methods == [METHOD_WHEELSPIN, METHOD_AUTOSHOW]


def test_classify_reward_only():
    kind, methods = classify_obtain("此车辆可能在季节性赛事或嘉年华游戏列表中作为奖励出现。")
    assert kind == OBTAIN_REWARD
    assert methods == [METHOD_REWARD]


def test_classify_unknown():
    kind, methods = classify_obtain("一些无关文字")
    assert kind == OBTAIN_UNKNOWN
    assert methods == []


# ----------------------------------------------------------------------------- frame detection
def _blank_frame(h=900, w=1600):
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :] = (40, 130, 120)            # teal page background
    return arr


def _fill_cell_image(arr, row, col, color):
    h, w = arr.shape[:2]
    x0, y0, x1, y1 = cell_image_box(row, col)
    arr[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = color


def test_is_placeholder_detects_gray_card():
    arr = _blank_frame()
    _fill_cell_image(arr, 1, 0, (225, 225, 225))     # neutral gray placeholder
    assert is_placeholder_cell(arr, 1, 0) is True


def test_is_placeholder_rejects_white_render():
    arr = _blank_frame()
    _fill_cell_image(arr, 1, 0, (242, 248, 241))     # tinted white studio bg = a car render
    assert is_placeholder_cell(arr, 1, 0) is False


def test_focused_cell_finds_lime_ring():
    arr = _blank_frame()
    h, w = arr.shape[:2]
    # draw a lime ring around the card box of (row=2, col=3)
    cx, cy = COL_CENTERS[3], ROW_CENTERS[2]
    x0, x1 = int((cx - 0.085) * w), int((cx + 0.085) * w)
    y0, y1 = int((cy - 0.115) * h), int((cy + 0.115) * h)
    lime = (200, 255, 0)
    arr[y0:y0 + 6, x0:x1] = lime
    arr[y1 - 6:y1, x0:x1] = lime
    arr[y0:y1, x0:x0 + 6] = lime
    arr[y0:y1, x1 - 6:x1] = lime
    assert focused_cell(arr) == (2, 3)


def test_focused_cell_none_when_no_ring():
    assert focused_cell(_blank_frame()) is None


def _name_item(row, col, text, dy=0.0):
    return SimpleNamespace(ncx=COL_CENTERS[col], ncy=ROW_CENTERS[row] + NAME_DY + dy, text=text)


def test_read_cell_name_picks_name_band():
    items = [
        _name_item(0, 0, "595 esseesse"),
        _name_item(0, 0, "1968 Abarth", dy=0.024),    # the year line, just below -> ignored
        _name_item(0, 4, "RSX Type S"),
    ]
    assert read_cell_name(items, 0, 0) == "595 esseesse"
    assert read_cell_name(items, 0, 4) == "RSX Type S"
    assert read_cell_name(items, 1, 2) == ""          # nothing there


def test_read_cell_name_skips_placeholder_text():
    items = [SimpleNamespace(ncx=COL_CENTERS[1], ncy=ROW_CENTERS[0] + NAME_DY, text="DISCOVER")]
    assert read_cell_name(items, 0, 1) == ""


# ----------------------------------------------------------------------------- traversal (FakeIO)
class FakeGridIO:
    """Models a scrolling 5-column collection grid. Each row is a list of cell dicts
    {name, placeholder, popup}. The cursor walks; the grid scrolls to keep it within 3 visible rows."""

    def __init__(self, rows):
        self.rows = rows
        self.top = 0
        self.cur_row = 0
        self.cur_col = 0
        self.presses = []
        self.starts = []          # car names we pressed 购买 (start) on
        self.dismissed = 0

    def focused(self):
        return True

    def activate(self):
        pass

    def pin_to_top(self):
        self.top = self.cur_row = self.cur_col = 0

    def read(self):
        cells = {}
        for vr in range(3):
            ar = self.top + vr
            for c in range(5):
                if ar < len(self.rows) and c < len(self.rows[ar]):
                    cd = self.rows[ar][c]
                    cells[(vr, c)] = Cell(cd["name"], cd["placeholder"])
                else:
                    cells[(vr, c)] = Cell("", False)
        vr = self.cur_row - self.top
        focus = (vr, self.cur_col) if 0 <= vr < 3 else None
        return GridView(on_grid=True, focused=focus, cells=cells)

    def move_to_col(self, row, col):
        self.cur_col = col
        return True

    def press(self, btn):
        self.presses.append(btn)
        if btn == "start":
            self.starts.append(self.rows[self.cur_row][self.cur_col]["name"])
        elif btn == "a":
            self.dismissed += 1

    def popup_text(self):
        return self.rows[self.cur_row][self.cur_col].get("popup", "")

    def next_row(self):
        if self.cur_row + 1 >= len(self.rows):
            return False
        self.cur_row += 1
        if self.cur_row - self.top > 2:
            self.top = self.cur_row - 2
        return True


def _cell(name, placeholder, popup=""):
    return {"name": name, "placeholder": placeholder, "popup": popup}


BUY = "此车可通过以下途径获得：车展。是否要从车展购买这辆车?"
LOTTERY = "此车可通过以下途径获得：抽奖,车展。是否要从车展购买这辆车?"
REWARD = "此车辆可能在季节性赛事或嘉年华游戏列表中作为奖励出现。"


def _grid():
    return [
        [_cell("595 esseesse", False), _cell("131", False), _cell("695 Biposto", True, REWARD),
         _cell("Integra Type R", False), _cell("RSX Type S", False)],
        [_cell("NSX Type S", True, REWARD), _cell("Integra A-Spec", False),
         _cell("Giulia Sprint", False), _cell("Giulia TZ2", True, BUY), _cell("33 Stradale", True, LOTTERY)],
        [_cell("155 Q4", True, BUY), _cell("8C", False), _cell("4C", True, BUY),
         _cell("Giulia Quad", False), _cell("Class 10", False)],
    ]


def test_survey_full_grid_catalogs_unowned_only():
    io = FakeGridIO(_grid())
    s = UnownedSurveyor(io, sleeper=lambda *_: None)
    reason = s.run()
    assert reason == "done"
    names = {r.name for r in s.results}
    assert names == {"695 Biposto", "NSX Type S", "Giulia TZ2", "33 Stradale", "155 Q4", "4C"}
    # 购买 was pressed ONLY on placeholders -- never on an owned/render car
    assert set(io.starts) == names
    assert io.dismissed == len(io.starts)        # every popup dismissed with A (no buys)


def test_survey_methods_and_summary():
    io = FakeGridIO(_grid())
    s = UnownedSurveyor(io, sleeper=lambda *_: None)
    s.run()
    by_name = {r.name: r for r in s.results}
    assert by_name["695 Biposto"].kind == OBTAIN_REWARD
    assert by_name["Giulia TZ2"].methods == [METHOD_AUTOSHOW]
    assert by_name["33 Stradale"].methods == [METHOD_WHEELSPIN, METHOD_AUTOSHOW]
    summary = s.summary()
    assert summary["total_unowned"] == 6
    assert summary["owned_seen"] == 9          # 4 + 2 + 3 owned/render cells across the 3 rows
    assert set(summary["by_method"][METHOD_REWARD]) == {"695 Biposto", "NSX Type S"}
    report = format_report(summary)
    assert "共 6 辆未拥有" in report
    assert "695 Biposto" in report


def test_survey_stop_event_halts():
    io = FakeGridIO(_grid())
    stop = threading.Event()

    calls = {"n": 0}
    orig = io.read

    def counting_read():
        calls["n"] += 1
        if calls["n"] >= 2:
            stop.set()
        return orig()

    io.read = counting_read
    s = UnownedSurveyor(io, sleeper=lambda *_: None, stop_event=stop)
    reason = s.run()
    assert reason == "stopped"


def test_survey_leaves_grid_reports_left():
    class OffGridIO(FakeGridIO):
        def read(self):
            return GridView(on_grid=False, focused=None, cells={})

    s = UnownedSurveyor(OffGridIO(_grid()), sleeper=lambda *_: None)
    assert s.run() == "left_grid"


def test_survey_single_row_grid_terminates():
    io = FakeGridIO([[_cell("Solo", True, BUY), _cell("Owned", False)]])
    s = UnownedSurveyor(io, sleeper=lambda *_: None)
    assert s.run() == "done"
    assert [r.name for r in s.results] == ["Solo"]
