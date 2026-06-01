"""Tests for v5.nav_runner wiring -- mocked recognizer/pad/focus (no game, no ONNX)."""
from types import SimpleNamespace

import focus
from v4.decision import normalize_button
from v5.nav_runner import V5Navigator


def _u(screen, selected_item=""):
    return SimpleNamespace(
        screen=screen, selected_item=selected_item, active_tab="",
        filter_state={}, scroll_state={}, ocr_regions=[],
    )


class Route:
    """A scripted 'game' whose screen advances one step per pad press."""

    def __init__(self, screens):
        self.screens = screens
        self.idx = 0

    def current(self):
        return _u(self.screens[self.idx])

    def advance(self):
        if self.idx < len(self.screens) - 1:
            self.idx += 1


class FakeRecognizer:
    def __init__(self, route):
        self.route = route

    def capture(self, full_ocr=True, region_ocr=True, max_age_ms=250.0):
        return SimpleNamespace(capture_method="sync", v3=self.route.current())


class FakePad:
    def __init__(self, route=None):
        self.route = route
        self.taps = []

    def tap(self, name, hold=0.1):
        self.taps.append(name)
        if self.route is not None:
            self.route.advance()

    def neutral(self):
        pass


def test_recognize_occlusion_fallback_on_dxcam_unknown(monkeypatch):
    monkeypatch.setattr(focus, "is_foreground", lambda title="Forza": True)
    calls = []

    class Rec:
        def capture(self, full_ocr=True, region_ocr=True, max_age_ms=250.0):
            calls.append(max_age_ms)
            if max_age_ms != 0.0:  # engine path returns an occluded -> unknown frame
                return SimpleNamespace(capture_method="dxcam", v3=_u("unknown"))
            return SimpleNamespace(capture_method="PrintWindow", v3=_u("race_menu"))

    nav = V5Navigator(recognizer=Rec(), use_capture_engine=False)
    v3 = nav.recognize()
    assert v3.screen == "race_menu"
    assert nav.fallbacks == 1
    assert 0.0 in calls  # forced a synchronous re-grab


def test_recognize_no_fallback_when_dxcam_reads_a_real_screen(monkeypatch):
    monkeypatch.setattr(focus, "is_foreground", lambda title="Forza": True)

    class Rec:
        def capture(self, full_ocr=True, region_ocr=True, max_age_ms=250.0):
            return SimpleNamespace(capture_method="dxcam", v3=_u("eventlab_events"))

    nav = V5Navigator(recognizer=Rec(), use_capture_engine=False)
    assert nav.recognize().screen == "eventlab_events"
    assert nav.fallbacks == 0


def test_recognize_returns_background_when_not_foreground(monkeypatch):
    monkeypatch.setattr(focus, "is_foreground", lambda title="Forza": False)
    captured = []

    class Rec:
        def capture(self, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(capture_method="sync", v3=_u("x"))

    nav = V5Navigator(recognizer=Rec(), use_capture_engine=False, require_foreground=True)
    assert nav.recognize().screen == "background"
    assert captured == []  # never captured while backgrounded


def test_decide_delegates_to_registry_next_button():
    nav = V5Navigator(goal="eventlab_events", recognizer=object(), use_capture_engine=False)
    act = nav.decide(_u("eventlab_home"))
    assert act.name == "route_step" and normalize_button(act.button) == "a"


def test_press_taps_pad_and_ignores_unknown_button():
    pad = FakePad()
    nav = V5Navigator(recognizer=object(), use_capture_engine=False, pad=pad)
    nav.press("a")
    nav.press("not_a_button")  # ignored, no crash
    assert pad.taps == ["a"]


def test_run_navigates_to_goal_with_fakes():
    route = Route(["eventlab_home", "eventlab_events"])
    pad = FakePad(route)
    nav = V5Navigator(
        goal="eventlab_events", require_foreground=False, use_capture_engine=False,
        recognizer=FakeRecognizer(route), pad=pad, engine=None, max_seconds=10.0,
    )
    result = nav.run()
    assert result.reason == "goal"
    assert pad.taps == ["a"] and result.last_screen == "eventlab_events"
