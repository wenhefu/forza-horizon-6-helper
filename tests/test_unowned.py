"""Tests for the buy-all-unowned loop (UnownedBuyer) with a fake IO.

The fragile, slow buy sub-flow now lives in UnownedBuyIO.buy_focused_car (phase-aware, tolerant
of the slow 推荐设计 load); the loop just orchestrates filter -> buy -> re-enter -> re-filter.

Invariants under test: never buys on an UNFILTERED grid (filter applied first every cycle); the
filter is re-applied every cycle (it resets on re-entry); dry-run never reports a purchase; the
loop terminates (max_cars / empty grid / stop) instead of looping forever; unlimited (max=None)
buys until the grid is empty.
"""
import threading

from v4.unowned_buyer import DISCONNECT, GRID, MENU, UnownedBuyer


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

    def press(self, b):
        self.presses.append(b)
        if self._state == DISCONNECT and b == "a":
            self._state = GRID          # controller reconnected

    def apply_unowned_filter(self):
        self.calls.append("apply_filter")
        if self._state == GRID:
            self._filtered = True
            return True
        return False

    def buy_focused_car(self, dry_run):
        self.calls.append(("buy", "dry" if dry_run else "real"))
        if not (self._state == GRID and self._filtered):
            return "no_car"
        if self.unowned <= 0:
            return "no_car"             # filtered grid empty -> done
        if dry_run:
            return "dry_seen"           # walked to confirm + cancelled; nothing bought
        self.unowned -= 1
        self._state = MENU              # a real buy ends back at the 购买与出售 menu
        self._filtered = False
        return "bought"

    def enter_showroom(self):
        self.calls.append("enter_showroom")
        self._state = GRID
        self._filtered = False          # the filter RESETS on re-entry
        return True


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
    assert ("buy", "dry") in io.calls          # walked into the (cancelled) buy
    assert ("buy", "real") not in io.calls     # never a real purchase


def test_buys_all_unowned_then_stops_when_grid_empty():
    io = FakeIO(unowned=2)
    b = _buyer(io, dry_run=False, max_cars=10)
    assert b.run() == "no_more_cars"
    assert b.bought == 2


def test_stops_at_max_cars():
    io = FakeIO(unowned=10)
    b = _buyer(io, dry_run=False, max_cars=3)
    assert b.run() == "max_cars"
    assert b.bought == 3


def test_unlimited_max_cars_buys_until_grid_empty():
    io = FakeIO(unowned=4)
    b = _buyer(io, dry_run=False, max_cars=None)
    assert b.run() == "no_more_cars"
    assert b.bought == 4


def test_filter_is_reapplied_every_cycle_before_buying():
    # The 未拥有 filter resets on grid re-entry, so it must be applied once per buy cycle and
    # ALWAYS immediately before the buy (never buy an unfiltered grid).
    io = FakeIO(unowned=2)
    _buyer(io, dry_run=False, max_cars=10).run()
    buys = [i for i, c in enumerate(io.calls) if c == ("buy", "real") or c == ("buy", "dry")]
    for i in buys:
        assert io.calls[i - 1] == "apply_filter"   # every buy is preceded by a filter-apply


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
