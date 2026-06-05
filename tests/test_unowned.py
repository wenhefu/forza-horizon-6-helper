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
    def __init__(self, *, focused=True, unowned=3, start=GRID, b_clears=False, disc_text=False,
                 nav_recovers=False):
        self._state = start
        self._filtered = False
        self._focused = focused
        self.unowned = unowned          # un-owned cars still left to buy
        self.b_clears = b_clears        # if True, pressing B on an unhandled screen -> back to grid
        self._disc_text = disc_text     # controller-disconnect modal detectable only by OCR text
        self.nav_recovers = nav_recovers  # does navigate_to_grid() succeed (reach the grid)?
        self.presses = []
        self.calls = []
        self.activate_calls = 0

    def controller_disconnected(self):
        return self._disc_text

    def navigate_to_grid(self):
        self.calls.append("navigate_to_grid")
        if self.nav_recovers:
            self._state = GRID
            self._filtered = False
            return True
        return False

    def focused(self):
        return self._focused

    def activate(self):
        self.activate_calls += 1
        self._focused = True

    def screen(self):
        return self._state

    def press(self, b):
        self.presses.append(b)
        if b == "a" and (self._state == DISCONNECT or self._disc_text):
            self._state = GRID          # A dismissed the disconnect modal -> reconnected
            self._disc_text = False
        elif b == "b" and self.b_clears and self._state not in (GRID, MENU, DISCONNECT):
            self._state = GRID          # B dismissed the stray popup -> back to the grid

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


def test_text_detected_controller_disconnect_is_dismissed_with_A():
    # The user's bug: the 控制器未连接 modal was mislabeled (unknown), so the loop didn't press A.
    # Now it's detected by OCR text and dismissed with A, then buying resumes.
    io = FakeIO(unowned=1, start="unknown", disc_text=True)
    b = _buyer(io, dry_run=False, max_cars=5)
    assert b.run() == "no_more_cars"
    assert "a" in io.presses                   # pressed A (确定) to reconnect
    assert b.bought == 1                        # recovered and bought the car


def test_stall_guard_presses_A_then_B_when_stuck():
    # When stuck on an unhandled screen, the guard tries A (dismiss/确定) before B.
    io = FakeIO(unowned=1, start="some_popup", b_clears=False)
    b = _buyer(io, dry_run=False, max_cars=5)
    b.run()
    assert "a" in io.presses and "b" in io.presses


def test_stall_guard_stops_cleanly_when_stuck_on_unhandled_screen():
    # An unrecognized screen (e.g. a popup) used to make the loop wait forever; now it tries to
    # re-orient to the grid and, if that keeps failing, stops cleanly with "stuck".
    io = FakeIO(unowned=1, start="some_popup", b_clears=False, nav_recovers=False)
    b = _buyer(io, dry_run=False, max_cars=5)
    assert b.run() == "stuck"
    assert "navigate_to_grid" in io.calls       # attempted the re-orient recovery


def test_stall_guard_recovers_if_B_dismisses_the_popup():
    # If B clears the stray popup, the loop unsticks and resumes buying.
    io = FakeIO(unowned=1, start="some_popup", b_clears=True)
    b = _buyer(io, dry_run=False, max_cars=5)
    assert b.run() == "no_more_cars"
    assert b.bought == 1


def test_stall_guard_re_orients_to_grid_and_resumes():
    # The real-world fix: when stuck (drift / mislabeled screen), navigate_to_grid() takes it
    # back to the 车展 grid and buying resumes.
    io = FakeIO(unowned=1, start="some_popup", b_clears=False, nav_recovers=True)
    b = _buyer(io, dry_run=False, max_cars=5)
    assert b.run() == "no_more_cars"
    assert "navigate_to_grid" in io.calls
    assert b.bought == 1
