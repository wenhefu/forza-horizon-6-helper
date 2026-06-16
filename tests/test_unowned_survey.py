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
    METHOD_BARNFIND,
    METHOD_MASTERY,
    METHOD_STORE,
    OBTAIN_BUY,
    OBTAIN_INFO,
    OBTAIN_REWARD,
    OBTAIN_BARNFIND,
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


# --- richer methods discovered in the live 139-car corpus -----------------------------------------
def test_classify_barnfind():
    kind, methods = classify_obtain("车辆收藏 | 四处探索，寻找关于该废弃车辆下落的线索... | 确定")
    assert kind == OBTAIN_BARNFIND
    assert methods == [METHOD_BARNFIND]


def test_classify_barnfind_garage_variant():
    # second live variant -- previously fell through to 未知 (24/112 cars on the live grid)
    kind, methods = classify_obtain("车辆收藏 | 听说这辆车被人遗弃在车房里... | 确定")
    assert kind == OBTAIN_BARNFIND
    assert methods == [METHOD_BARNFIND]


def test_classify_collection_category_plus_autoshow():
    kind, methods = classify_obtain(
        '车辆收藏 | 此车可通过以下途径获得：在收集簿的"危险标志"类别，车展 | 是否要从车展购买这辆车？ | 取消 | 确认'
    )
    assert kind == OBTAIN_BUY                      # 车展 present -> buyable
    assert "收集簿·危险标志" in methods
    assert METHOD_AUTOSHOW in methods


def test_classify_wheelspin_plus_reward_is_info():
    # 抽奖 only (no 车展) + the reward note, single 确定 -> info kind
    kind, methods = classify_obtain(
        "车辆收藏 | 此车可通过以下途径获得：抽奖 | 此车辆可能在季节赛事或嘉年华游戏列表中作为奖励出现。 | 确定"
    )
    assert kind == OBTAIN_INFO
    assert METHOD_WHEELSPIN in methods and METHOD_REWARD in methods


def test_classify_mastery_and_store():
    assert METHOD_MASTERY in classify_obtain("此车可通过以下途径获得：车辆专精树")[1]
    assert METHOD_STORE in classify_obtain("此车可通过以下途径获得：商店附加内容")[1]


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
    """A press-driven 5-column collection-grid simulator. Each row is a list of cell dicts
    {name, placeholder, popup} (rows may be partial). dpad presses move the cursor (clamped at the
    real car edges) and scroll the grid to keep the cursor within the 3 visible rows -- exactly what
    the snake walk drives against."""

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

    def _rowlen(self, r):
        return len(self.rows[r]) if 0 <= r < len(self.rows) else 0

    def pin_to_top(self):
        self.top = self.cur_row = self.cur_col = 0

    def read(self):
        cells = {}
        for vr in range(3):
            ar = self.top + vr
            for c in range(5):
                if 0 <= ar < len(self.rows) and c < len(self.rows[ar]):
                    cd = self.rows[ar][c]
                    cells[(vr, c)] = Cell(cd["name"], cd["placeholder"])
                else:
                    cells[(vr, c)] = Cell("", False)
        vr = self.cur_row - self.top
        focus = (vr, self.cur_col) if 0 <= vr < 3 else None
        return GridView(on_grid=True, focused=focus, cells=cells)

    def press(self, btn):
        self.presses.append(btn)
        if btn == "start":
            row = self.rows[self.cur_row]
            if self.cur_col < len(row):
                self.starts.append(row[self.cur_col]["name"])
        elif btn == "a":
            self.dismissed += 1
        elif btn == "dpad_right":
            self.cur_col = min(self.cur_col + 1, max(0, self._rowlen(self.cur_row) - 1), 4)
        elif btn == "dpad_left":
            self.cur_col = max(self.cur_col - 1, 0)
        elif btn == "dpad_up":
            if self.cur_row > 0:
                self.cur_row -= 1
                if self.cur_row < self.top:
                    self.top = self.cur_row
                self.cur_col = min(self.cur_col, max(0, self._rowlen(self.cur_row) - 1))
        elif btn == "dpad_down":
            if self.cur_row < len(self.rows) - 1:
                self.cur_row += 1
                if self.cur_row - self.top > 2:
                    self.top = self.cur_row - 2
                self.cur_col = min(self.cur_col, max(0, self._rowlen(self.cur_row) - 1))

    def popup_text(self):
        row = self.rows[self.cur_row]
        return row[self.cur_col].get("popup", "") if self.cur_col < len(row) else ""


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


def test_collect_all_records_every_car_corpus():
    io = FakeGridIO(_grid())
    corpus = []
    s = UnownedSurveyor(
        io, sleeper=lambda *_: None, collect_all=True,
        on_corpus=lambda n, p, t: corpus.append((n, p, t)),
    )
    assert s.run() == "done"
    all_names = {cell["name"] for row in _grid() for cell in row}
    assert {c[0] for c in corpus} == all_names         # corpus has EVERY car (owned + un-owned)
    assert set(io.starts) == all_names                 # 购买 pressed on every car
    flags = {c[0]: c[1] for c in corpus}
    assert flags["695 Biposto"] is True and flags["595 esseesse"] is False
    text = {c[0]: c[2] for c in corpus}
    assert "车展" in text["Giulia TZ2"]
    assert len(s.results) == 6                          # un-owned still classified into results


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


def test_survey_recovers_from_stray_modal():
    """A controller-disconnect modal / stray popup left on top of the grid is dismissed with A,
    then the survey proceeds -- it must NOT bail out as 'left_grid'."""
    base = FakeGridIO([[_cell("A", True, BUY), _cell("B", False)]])
    seq = [
        GridView(on_grid=False, focused=None, cells={}, text="控制器未连接 | 请重新连接控制器。 | 确定"),
        GridView(on_grid=False, focused=None, cells={}, text="车辆收藏 | 是否要从车展购买这辆车？ | 取消 | 确认"),
    ]
    presses = []

    class WrapIO:
        def __init__(self):
            self.i = 0

        def focused(self):
            return True

        def activate(self):
            pass

        def pin_to_top(self):
            base.pin_to_top()

        def read(self):
            if self.i < len(seq):
                gv = seq[self.i]
                self.i += 1
                return gv
            return base.read()

        def press(self, b):
            presses.append(b)
            base.press(b)

        def popup_text(self):
            return base.popup_text()

    s = UnownedSurveyor(WrapIO(), sleeper=lambda *_: None)
    assert s.run() == "done"
    assert presses.count("a") >= 2          # dismissed the disconnect modal + the stray popup
    assert [r.name for r in s.results] == ["A"]


def test_snake_catches_every_placeholder_in_a_row():
    """Regression for the row-batch bug that skipped MIDDLE placeholders: a row of all-placeholders
    + multi-placeholder rows must be caught completely (the cursor visits each cell)."""
    grid = [
        [_cell("P1", True, BUY), _cell("P2", True, REWARD), _cell("P3", True, LOTTERY),
         _cell("P4", True, BUY), _cell("P5", True, REWARD)],                          # ALL placeholders
        [_cell("o1", False), _cell("M1", True, BUY), _cell("o2", False),
         _cell("M2", True, BUY), _cell("o3", False)],                                 # placeholders at 1,3
        [_cell("o4", False), _cell("o5", False), _cell("P6", True, REWARD),
         _cell("o6", False), _cell("o7", False)],                                     # placeholder in the middle
    ]
    io = FakeGridIO(grid)
    s = UnownedSurveyor(io, sleeper=lambda *_: None)
    assert s.run() == "done"
    assert {r.name for r in s.results} == {"P1", "P2", "P3", "P4", "P5", "M1", "M2", "P6"}


def test_snake_handles_partial_last_row():
    grid = [
        [_cell("A", True, BUY), _cell("B", False), _cell("C", True, REWARD), _cell("D", False), _cell("E", False)],
        [_cell("F", True, BUY), _cell("G", False)],          # partial last row (2 cars)
    ]
    io = FakeGridIO(grid)
    s = UnownedSurveyor(io, sleeper=lambda *_: None)
    assert s.run() == "done"
    assert {r.name for r in s.results} == {"A", "C", "F"}


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
