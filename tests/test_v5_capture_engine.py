"""Tests for v5.capture_engine -- no live game, no real dxcam (all mocked/bounded)."""
import sys
import time
from types import SimpleNamespace

import numpy as np

from v5 import capture_engine as ce
from v5.capture_engine import CaptureEngine, ClientRect, bgr_to_frame, resolve_client_rect


# --- bgr_to_frame: byte layout matches the GDI Frame ------------------------

def test_bgr_to_frame_matches_gdi_byte_layout():
    # 2x2 BGR image; channels are B, G, R per the dxcam/GDI convention.
    arr = np.array(
        [[[10, 20, 30], [40, 50, 60]], [[70, 80, 90], [100, 110, 120]]],
        dtype=np.uint8,
    )
    frame = bgr_to_frame(arr)
    assert frame.width == 2 and frame.height == 2
    assert len(frame.bgra) == 2 * 2 * 4
    # Frame.iter_region yields (R, G, B); top-down, row-major.
    pixels = list(frame.iter_region(0.0, 0.0, 1.0, 1.0, step=1))
    assert pixels == [(30, 20, 10), (60, 50, 40), (90, 80, 70), (120, 110, 100)]


def test_bgr_to_frame_bgra_passthrough():
    arr = np.zeros((3, 4, 4), dtype=np.uint8)
    arr[..., 3] = 7  # distinct alpha
    frame = bgr_to_frame(arr)
    assert frame.width == 4 and frame.height == 3 and len(frame.bgra) == 4 * 3 * 4
    assert frame.bgra[3] == 7  # alpha preserved


# --- resolve_client_rect: fake ctypes via byref._obj -----------------------

class _FakeUser32:
    def __init__(self, w, h, x, y):
        self.w, self.h, self.x, self.y = w, h, x, y

    def GetClientRect(self, hwnd, ref):
        rect = ref._obj
        rect.left, rect.top, rect.right, rect.bottom = 0, 0, self.w, self.h
        return 1

    def ClientToScreen(self, hwnd, ref):
        point = ref._obj
        point.x, point.y = self.x, self.y
        return 1


def test_resolve_client_rect_offset(monkeypatch):
    monkeypatch.setattr(ce, "user32", _FakeUser32(1920, 1080, 100, 40))
    assert resolve_client_rect(123) == ClientRect(100, 40, 1920, 1080)
    assert resolve_client_rect(123).region == (100, 40, 2020, 1120)


def test_resolve_client_rect_none_when_minimized(monkeypatch):
    monkeypatch.setattr(ce, "user32", _FakeUser32(0, 0, 0, 0))
    assert resolve_client_rect(123) is None


def test_resolve_client_rect_none_when_no_hwnd():
    assert resolve_client_rect(0) is None


# --- engine: dxcam unavailable -> transparent no-op ------------------------

def test_engine_unavailable_when_dxcam_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "dxcam", None)  # `import dxcam` -> ImportError
    eng = CaptureEngine(title="Forza")
    try:
        assert eng.start() is False
        assert eng.available is False
        assert eng.is_running() is False
        frame, age = eng.get_latest_frame()
        assert frame is None and age == float("inf")
    finally:
        eng.stop()  # idempotent even though no thread started


# --- engine: publishes latest frame with a fake dxcam ----------------------

class _FakeCamera:
    def __init__(self):
        self.calls = 0
        self.regions = []

    def grab(self, region=None):
        self.calls += 1
        self.regions.append(region)
        if self.calls % 2 == 1:
            return np.full((3, 4, 4), 9, dtype=np.uint8)  # BGRA frame
        return None  # dxcam returns None when the framebuffer is unchanged

    def release(self):
        pass


def test_engine_publishes_latest_with_fake_dxcam(monkeypatch):
    cam = _FakeCamera()
    monkeypatch.setitem(sys.modules, "dxcam", SimpleNamespace(create=lambda **kw: cam))
    monkeypatch.setattr(ce.focus, "find_window", lambda title: 123)
    monkeypatch.setattr(ce, "resolve_client_rect", lambda hwnd: ClientRect(0, 0, 4, 3))
    eng = CaptureEngine(title="Forza", target_fps=200)
    try:
        assert eng.start() is True and eng.available is True
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and eng.stats()["frames"] < 1:
            time.sleep(0.01)
        frame, age = eng.get_latest_frame()
        assert frame is not None and frame.width == 4 and frame.height == 3
        assert age < 2000.0
        # the captured region was the resolved client rect
        assert cam.regions and cam.regions[0] == (0, 0, 4, 3)
        # None grabs (unchanged frames) are counted as drops, not errors
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and eng.stats()["drops"] < 1:
            time.sleep(0.01)
        assert eng.stats()["drops"] >= 1
        assert eng.stats()["errors"] == 0
    finally:
        eng.stop()
    assert eng.is_running() is False


# --- V4Recognizer opt-in integration ---------------------------------------

def _bare_recognizer(capture_engine=None):
    from v4.recognizer import V4Recognizer

    inst = V4Recognizer.__new__(V4Recognizer)
    inst.title = "Forza"
    inst.min_confidence = 0.42
    inst.capture_engine = capture_engine
    inst.ocr = SimpleNamespace(read_frame=lambda *a, **k: [])
    inst.hybrid = SimpleNamespace(analyze_frame=lambda *a, **k: SimpleNamespace(to_dict=lambda: {}))
    inst.smart_detector = SimpleNamespace(detect=lambda *a, **k: SimpleNamespace(state="", confidence=0.0))
    return inst


def test_v4recognizer_uses_engine_when_fresh(monkeypatch):
    from v4 import recognizer as rec

    dummy_frame = SimpleNamespace()
    eng = SimpleNamespace(is_running=lambda: True, get_latest_frame=lambda: (dummy_frame, 5.0))
    inst = _bare_recognizer(capture_engine=eng)
    monkeypatch.setattr(rec.focus, "find_window", lambda title: 123)
    monkeypatch.setattr(rec.focus, "window_title", lambda hwnd: "Forza Horizon 6")

    def _boom(hwnd):
        raise AssertionError("synchronous capture must not run when the engine frame is fresh")

    monkeypatch.setattr(rec, "capture_client_printwindow", _boom)
    monkeypatch.setattr(rec, "capture_client", _boom)
    snap = inst.capture(full_ocr=False, region_ocr=True)
    assert snap.capture_method == "dxcam"
    assert snap.frame is dummy_frame


def test_v4recognizer_falls_back_when_no_engine_or_stale(monkeypatch):
    from v4 import recognizer as rec

    dummy_frame = SimpleNamespace()
    monkeypatch.setattr(rec.focus, "find_window", lambda title: 123)
    monkeypatch.setattr(rec.focus, "window_title", lambda hwnd: "Forza Horizon 6")
    monkeypatch.setattr(rec, "capture_client_printwindow", lambda hwnd: dummy_frame)

    # (a) no engine -> default synchronous path (V4 behavior unchanged)
    assert _bare_recognizer(None).capture(full_ocr=False).capture_method == "PrintWindow"

    # (b) engine present but its latest frame is stale -> falls back to sync grab
    stale = SimpleNamespace(is_running=lambda: True, get_latest_frame=lambda: (dummy_frame, 9999.0))
    assert _bare_recognizer(stale).capture(full_ocr=False).capture_method == "PrintWindow"
