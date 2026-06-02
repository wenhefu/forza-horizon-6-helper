"""Tests for v5.reactor -- event-driven loop, fake clock + fake game (no real time)."""
import threading
from types import SimpleNamespace

from v5.reactor import EventReactor


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(0.0, seconds)


def u(screen, selected_item="", active_tab=""):
    return SimpleNamespace(
        screen=screen, selected_item=selected_item, active_tab=active_tab,
        filter_state={}, scroll_state={},
    )


class Game:
    """Advances to the next screen immediately on each press."""

    def __init__(self, screens):
        self.screens = screens
        self.idx = 0
        self.presses = []

    def recognize(self):
        return u(self.screens[self.idx])

    def press(self, button):
        self.presses.append(button)
        if self.idx < len(self.screens) - 1:
            self.idx += 1


class LaggyGame:
    """The press lands two recognizes later (so the reactor must WATCH for it)."""

    def __init__(self, screens):
        self.screens = screens
        self.idx = 0
        self.presses = []
        self._countdown = 0

    def recognize(self):
        if self._countdown > 0:
            self._countdown -= 1
            if self._countdown == 0 and self.idx < len(self.screens) - 1:
                self.idx += 1
        return u(self.screens[self.idx])

    def press(self, button):
        self.presses.append(button)
        self._countdown = 2


def step_decide(goal):
    def decide(understanding):
        if understanding.screen == goal:
            return SimpleNamespace(button="", name="arrived", terminal=True)
        return SimpleNamespace(button="A", name="step", terminal=False)

    return decide


def test_reactor_reaches_goal_through_screens():
    clk, game = Clock(), Game(["s0", "s1", "s2", "GOAL"])
    res = EventReactor(game.recognize, step_decide("GOAL"), game.press,
                       now=clk.now, sleep=clk.sleep).run(max_seconds=100)
    assert res.reason == "goal"
    assert res.steps == 3 and game.presses == ["a", "a", "a"]
    assert res.last_screen == "GOAL"


def test_reactor_watches_for_change_without_fixed_sleep():
    clk, game = Clock(), LaggyGame(["s0", "GOAL"])
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clk.sleep(seconds)

    res = EventReactor(game.recognize, step_decide("GOAL"), game.press,
                       now=clk.now, sleep=sleep, poll_interval=0.04, step_timeout=2.5).run(max_seconds=100)
    assert res.reason == "goal"
    assert sleeps, "should have polled while watching for the press to land"
    # never slept more than the poll interval -> no fixed 0.85-1.15s settle
    assert all(s <= 0.04 + 1e-9 for s in sleeps)


def test_reactor_waits_on_empty_button_then_arrives():
    clk = Clock()
    calls = {"n": 0}

    def recognize():
        calls["n"] += 1
        return u("loading" if calls["n"] <= 2 else "menu")

    def decide(understanding):
        if understanding.screen == "loading":
            return SimpleNamespace(button="", name="wait_loading")
        return SimpleNamespace(button="A", name="arrived", terminal=True)

    presses = []
    res = EventReactor(recognize, decide, lambda b: presses.append(b),
                       now=clk.now, sleep=clk.sleep, stall_seconds=100).run(max_seconds=100)
    assert res.reason == "goal"
    assert presses == []  # waited through loading, never blind-pressed


def test_reactor_stalls_when_no_progress():
    clk = Clock()
    res = EventReactor(lambda: u("frozen"),
                       lambda x: SimpleNamespace(button="", name="wait"),
                       lambda b: None,
                       now=clk.now, sleep=clk.sleep, poll_interval=0.05, stall_seconds=1.0).run(max_seconds=100)
    assert res.reason == "stalled"


def test_reactor_represses_on_step_timeout():
    clk = Clock()
    presses = []
    # game never advances on press; decide keeps pressing A
    res = EventReactor(lambda: u("stuck"),
                       lambda x: SimpleNamespace(button="A", name="step"),
                       lambda b: presses.append(b),
                       now=clk.now, sleep=clk.sleep, poll_interval=0.05, step_timeout=0.5).run(max_seconds=3.0)
    assert res.reason == "timeout"
    assert len(presses) >= 2  # re-pressed after each step timeout (not hung)


def test_reactor_stop_event_returns_stopped():
    stop = threading.Event()
    stop.set()
    res = EventReactor(lambda: u("x"), lambda x: SimpleNamespace(button="A", name="s"),
                       lambda b: None, stop_event=stop).run()
    assert res.reason == "stopped"


def test_reactor_max_seconds_timeout():
    clk = Clock()
    res = EventReactor(lambda: u("x"), lambda x: SimpleNamespace(button="", name="wait"),
                       lambda b: None, now=clk.now, sleep=clk.sleep,
                       poll_interval=0.1, stall_seconds=100).run(max_seconds=0.5)
    assert res.reason == "timeout"


class ScriptedFrames:
    """Returns a fixed screen per recognize() (independent of presses), recording presses.

    Models a real menu transition: after the press that opens a popup, the first
    frame is a mid-transition misread before the page settles.
    """

    def __init__(self, frames):
        self.frames = frames
        self.i = 0
        self.presses = []

    def recognize(self):
        scr = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return u(scr)

    def press(self, button):
        self.presses.append(button)


def _bad_on_transient_decide(seen):
    def decide(understanding):
        seen.append(understanding.screen)
        if understanding.screen == "GOAL":
            return SimpleNamespace(button="", name="arrived", terminal=True)
        if understanding.screen == "transient":
            return SimpleNamespace(button="X", name="reacted_to_misread")
        return SimpleNamespace(button="A", name="step")

    return decide


def test_settle_polls_skips_one_frame_transition_misread():
    # s0 --press--> [transient (1-frame misread)] -> GOAL (settled). settle_polls=1
    # must wait for the stable GOAL and never decide on the transient.
    frames = ScriptedFrames(["s0", "transient", "GOAL", "GOAL", "GOAL", "GOAL"])
    seen = []
    clk = Clock()
    res = EventReactor(frames.recognize, _bad_on_transient_decide(seen), frames.press,
                       now=clk.now, sleep=clk.sleep, settle_polls=1,
                       step_timeout=2.5, poll_interval=0.04).run(max_seconds=100)
    assert res.reason == "goal"
    assert frames.presses == ["a"]          # only the deliberate step, no stray "x"
    assert "transient" not in seen          # the 1-frame misread was never decided on


def test_settle_polls_zero_reacts_to_first_change():
    # The original behavior (default 0): react to the first changed frame, misread included.
    frames = ScriptedFrames(["s0", "transient", "GOAL", "GOAL"])
    seen = []
    clk = Clock()
    res = EventReactor(frames.recognize, _bad_on_transient_decide(seen), frames.press,
                       now=clk.now, sleep=clk.sleep, settle_polls=0,
                       step_timeout=2.5, poll_interval=0.04).run(max_seconds=100)
    assert "transient" in seen              # reacted to the transient (and pressed "x")
    assert "x" in frames.presses
