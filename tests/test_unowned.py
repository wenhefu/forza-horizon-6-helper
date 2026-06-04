"""Tests for the buy-all-unowned loop (UnownedBuyer) with a fake IO that scripts the live-mapped
flow: grid --apply filter--> grid --buy--> design --Y--> color --A--> preview --A--> confirm
--A--> showcase --B--> carview --B--> menu --enter--> grid (filter reset) -> repeat.

Safety invariants under test: never buys on an UNFILTERED grid (filter is applied first every
cycle); dry-run CANCELS at the confirm dialog (never spends); the loop terminates (max_cars /
empty grid) instead of looping forever.
"""
import threading

from v4.unowned_buyer import (
    CARVIEW,
    COLOR,
    CONFIRM,
    DESIGN,
    DISCONNECT,
    GRID,
    MENU,
    PREVIEW,
    SHOWCASE,
    UnownedBuyer,
)


class FakeIO:
    def __init__(self, *, focused=True, unowned=3, start=GRID):
        self._state = start
        self._filtered = False
        self._focused = focused
        self.unowned = unowned          # un-owned cars still left to buy
        self.presses = []
        self.calls = []
        self.activate_calls = 0

    def focused(self):
        return self._focused

    def activate(self):
        self.activate_calls += 1
        self._focused = True

    def screen(self):
        return self._state

    def read_price(self):
        return "850,000"

    def press(self, b):
        self.presses.append(b)
        st = self._state
        if st == DESIGN and b == "y":
            self._state = COLOR
        elif st == COLOR and b == "a":
            self._state = PREVIEW
        elif st == PREVIEW and b == "a":
            self._state = CONFIRM
        elif st == CONFIRM and b == "b":       # dry-run cancel
            self._state = GRID
            self._filtered = False
        elif st == SHOWCASE and b == "b":
            self._state = CARVIEW
        elif st == CARVIEW and b == "b":
            self._state = MENU
        elif st == DISCONNECT and b == "a":
            self._state = GRID

    def apply_unowned_filter(self):
        self.calls.append("apply_filter")
        if self._state == GRID:
            self._filtered = True
            return True
        return False

    def open_buy(self):
        self.calls.append("open_buy")
        if self._state == GRID and self._filtered and self.unowned > 0:
            self._state = DESIGN
            return True
        return False

    def confirm_buy(self):
        self.calls.append("confirm_buy")
        self._state = SHOWCASE
        self.unowned -= 1

    def enter_showroom(self):
        self.calls.append("enter_showroom")
        self._state = GRID
        self._filtered = False


def _buyer(io, **kw):
    kw.setdefault("sleeper", lambda s: None)
    kw.setdefault("max_minutes", 999)
    return UnownedBuyer(io, **kw)


def test_dry_run_walks_to_confirm_then_cancels_without_buying():
    io = FakeIO(unowned=3)
    b = _buyer(io, dry_run=True)
    assert b.run() == "dry_done"
    assert b.bought == 0
    assert "apply_filter" in io.calls          # filtered first
    assert "open_buy" in io.calls              # walked into the buy flow
    assert "confirm_buy" not in io.calls       # but NEVER actually bought
    assert "b" in io.presses                   # cancelled at the confirm dialog


def test_buys_all_unowned_then_stops_when_grid_empty():
    io = FakeIO(unowned=2)
    b = _buyer(io, dry_run=False, max_cars=10)
    assert b.run() == "no_more_cars"
    assert b.bought == 2
    assert io.calls.count("confirm_buy") == 2


def test_stops_at_max_cars():
    io = FakeIO(unowned=10)
    b = _buyer(io, dry_run=False, max_cars=3)
    assert b.run() == "max_cars"
    assert b.bought == 3


def test_filter_is_reapplied_every_cycle_before_buying():
    # The 未拥有 filter resets on grid re-entry, so it must be applied once per buy cycle and
    # ALWAYS before the buy (never buy an unfiltered grid).
    io = FakeIO(unowned=2)
    b = _buyer(io, dry_run=False, max_cars=10)
    b.run()
    # one apply per buy + one final (empty) check; never an open_buy without a preceding filter
    assert io.calls.count("apply_filter") == io.calls.count("open_buy")
    # every open_buy is immediately preceded by an apply_filter
    for i, c in enumerate(io.calls):
        if c == "open_buy":
            assert io.calls[i - 1] == "apply_filter"


def test_empty_filtered_grid_terminates_immediately():
    io = FakeIO(unowned=0)
    b = _buyer(io, dry_run=False, max_cars=5)
    assert b.run() == "no_more_cars"
    assert b.bought == 0


def test_dismisses_controller_disconnect():
    io = FakeIO(unowned=1, start=DISCONNECT)
    b = _buyer(io, dry_run=False, max_cars=1)
    b.run()
    assert "a" in io.presses                   # pressed A to reconnect


def test_stops_on_stop_event():
    stop = threading.Event()
    stop.set()
    io = FakeIO(unowned=5)
    b = _buyer(io, dry_run=False, max_cars=5, stop_event=stop)
    assert b.run() == "stopped"
    assert b.bought == 0


def test_auto_focus_brings_game_forward():
    io = FakeIO(unowned=1, focused=False)
    b = _buyer(io, dry_run=True, auto_focus=True)
    b.run()
    assert io.activate_calls >= 1
