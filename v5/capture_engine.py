"""Continuous background screen-capture engine (dxcam) for the Forza helper.

A daemon thread captures the game's CLIENT region at a target FPS via dxcam
(DXGI Desktop Duplication) and exposes the latest frame as the existing
``window_capture.Frame`` (top-down BGRA bytes). Recognition (V3 hybrid / V4) is
stateless and frame-source-agnostic, so this drops in transparently.

Design notes:
- ``dxcam`` is imported LAZILY inside the engine. If it is missing or fails, the
  engine becomes a no-op (``available`` False, ``get_latest_frame`` returns
  ``(None, inf)``) and the V4 recognizer keeps using its synchronous GDI capture.
  So the friend's PC always works, with or without dxcam.
- Read-only screen capture only -- inside the project safety boundary (no inject,
  no hook, no fake-focus, no game-file modification).
- We reuse ``window_capture``'s already-configured ctypes (``user32``, ``RECT``,
  ``POINT`` with GetClientRect/ClientToScreen prototypes) and its per-monitor DPI
  awareness (enabled on import), so client-rect math matches dxcam's physical
  pixels and the produced ``Frame`` is byte-identical to the GDI path.
- OCCLUSION CONSTRAINT: dxcam (Desktop Duplication) captures what is VISIBLE on
  screen, unlike PrintWindow which renders the window's OWN content even when
  occluded. So the game's client area must be unoccluded -- consistent with the
  tool's existing "keep Forza in the foreground" requirement. If another window
  overlaps the game, dxcam returns that window's pixels and the recognizer sees
  an ``unknown`` screen; the V4 recognizer then falls back to PrintWindow only if
  the engine frame is stale, so the consumer (phase-3 wiring) should treat a dxcam
  ``unknown`` as a cue to re-grab via the synchronous path.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from dataclasses import dataclass

import focus
from window_capture import POINT, RECT, Frame, user32  # reuse configured ctypes + DPI awareness


@dataclass(frozen=True)
class ClientRect:
    """Screen-coordinate rectangle of a window's client (render) area."""

    left: int
    top: int
    width: int
    height: int

    @property
    def region(self) -> tuple[int, int, int, int]:
        # dxcam region is (left, top, right, bottom) with right/bottom EXCLUSIVE.
        return (self.left, self.top, self.left + self.width, self.top + self.height)


def resolve_client_rect(hwnd: int | None) -> ClientRect | None:
    """Screen rect of hwnd's CLIENT area, or None if the window is gone/minimized.

    Uses window_capture's GetClientRect + ClientToScreen (physical pixels under the
    per-monitor DPI awareness that window_capture enables on import).
    """
    if not hwnd:
        return None
    try:
        rect = RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:  # minimized windows report ~0 size
            return None
        pt = POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            return None
        return ClientRect(int(pt.x), int(pt.y), int(width), int(height))
    except Exception:
        return None


def bgr_to_frame(arr) -> Frame:
    """Convert a dxcam numpy array (BGRA or BGR, top-down) into a window_capture.Frame.

    The bytes are laid out exactly like the GDI path: B, G, R, A per pixel, rows
    top-to-bottom, stride = width*4 -- so Frame.iter_region reads identical (R,G,B).
    """
    import numpy as np

    if arr.ndim != 3 or arr.shape[2] not in (3, 4):
        raise ValueError(f"unexpected capture array shape: {getattr(arr, 'shape', None)}")
    height = int(arr.shape[0])
    width = int(arr.shape[1])
    if arr.shape[2] == 4:
        bgra = np.ascontiguousarray(arr, dtype=np.uint8)
    else:  # 3-channel BGR -> append opaque alpha
        bgra = np.empty((height, width, 4), dtype=np.uint8)
        bgra[:, :, :3] = arr  # dxcam BGR order is already B, G, R
        bgra[:, :, 3] = 255
    return Frame(width, height, bgra.tobytes())


class CaptureEngine:
    """Background daemon thread exposing the latest game-client frame via dxcam.

    Opt-in: construct one and pass it to ``V4Recognizer(capture_engine=...)``. If
    dxcam is unavailable the engine no-ops and the recognizer falls back to its
    synchronous capture -- V4 default behavior is unaffected when no engine is set.
    """

    def __init__(
        self,
        title: str = "Forza",
        target_fps: float = 60.0,
        rect_refresh_interval: float = 0.5,
        logger=None,
        output_idx: int | None = None,
    ):
        self.title = title
        self.target_fps = max(1.0, float(target_fps))
        self.rect_refresh_interval = max(0.05, float(rect_refresh_interval))
        self.logger = logger or logging.getLogger("forza6helper.v5.capture")
        self.output_idx = output_idx
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: Frame | None = None
        self._latest_ts = 0.0
        self._cam = None
        self._dxcam = None
        self._rect: ClientRect | None = None
        self._available = False
        self._frames = 0
        self._drops = 0
        self._errors = 0
        self._last_error = ""

    # -- lifecycle ---------------------------------------------------------
    def _lazy_init(self) -> bool:
        try:
            import dxcam  # noqa: PLC0415 (intentional lazy import)
        except Exception as exc:  # ImportError or native-load failure
            self._last_error = f"import dxcam failed: {exc}"
            self.logger.info("V5 capture: dxcam unavailable (%s); using window_capture fallback.", exc)
            return False
        self._dxcam = dxcam
        try:
            idx = 0 if self.output_idx is None else int(self.output_idx)
            self._cam = dxcam.create(output_idx=idx, output_color="BGRA")
            if self._cam is None:
                self._last_error = "dxcam.create returned None"
                self.logger.info("V5 capture: dxcam.create returned None; fallback.")
                return False
        except Exception as exc:
            self._last_error = f"dxcam.create failed: {exc}"
            self.logger.info("V5 capture: dxcam.create failed (%s); fallback.", exc)
            self._cam = None
            return False
        return True

    def start(self) -> bool:
        """Start the capture thread. Returns False (no-op) if dxcam is unavailable."""
        if self._thread and self._thread.is_alive():
            return self._available
        self._stop.clear()
        if not self._lazy_init():
            self._available = False
            self._thread = None
            return False
        self._available = True
        self._thread = threading.Thread(target=self._run, name="v5-capture", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        cam = self._cam
        self._cam = None
        if cam is not None:
            for closer in ("release", "stop"):
                try:
                    getattr(cam, closer)()
                    break
                except Exception:
                    continue
        self._available = False

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def available(self) -> bool:
        return self._available

    # -- consumer API (thread-safe) ---------------------------------------
    def get_latest_frame(self) -> tuple[Frame | None, float]:
        """Return (latest_frame, age_ms). (None, inf) if nothing captured yet."""
        with self._lock:
            frame = self._latest
            ts = self._latest_ts
        if frame is None:
            return None, float("inf")
        return frame, (time.monotonic() - ts) * 1000.0

    def stats(self) -> dict:
        with self._lock:
            rect = self._rect
            return {
                "available": self._available,
                "running": self.is_running(),
                "frames": self._frames,
                "drops": self._drops,
                "errors": self._errors,
                "last_error": self._last_error,
                "rect": (rect.left, rect.top, rect.width, rect.height) if rect else None,
            }

    # -- worker ------------------------------------------------------------
    def _refresh_rect(self) -> ClientRect | None:
        hwnd = focus.find_window(self.title)
        rect = resolve_client_rect(hwnd) if hwnd else None
        with self._lock:
            self._rect = rect
        return rect

    def _run(self) -> None:
        period = 1.0 / self.target_fps
        last_rect_check = 0.0
        try:
            while not self._stop.is_set():
                loop_start = time.monotonic()
                rect = self._rect
                if rect is None or (loop_start - last_rect_check) >= self.rect_refresh_interval:
                    rect = self._refresh_rect()
                    last_rect_check = loop_start
                if rect is None:
                    # window not found / minimized: keep the last frame, back off.
                    self._stop.wait(period * 4)
                    continue
                try:
                    arr = self._cam.grab(region=rect.region)
                except Exception as exc:
                    self._errors += 1
                    self._last_error = f"grab failed: {exc}"
                    with self._lock:
                        self._rect = None  # force re-resolve next loop
                    self._stop.wait(period * 4)
                    continue
                if arr is None:
                    # dxcam returns None when the framebuffer is unchanged -> keep last.
                    self._drops += 1
                else:
                    try:
                        frame = bgr_to_frame(arr)
                    except Exception as exc:
                        self._errors += 1
                        self._last_error = f"convert failed: {exc}"
                        frame = None
                    if frame is not None:
                        with self._lock:
                            self._latest = frame
                            self._latest_ts = time.monotonic()
                            self._frames += 1
                remaining = period - (time.monotonic() - loop_start)
                if remaining > 0:
                    self._stop.wait(remaining)
        except Exception as exc:  # never let the thread die silently
            self._errors += 1
            self._last_error = f"capture loop crashed: {exc}"
            self.logger.exception("V5 capture loop crashed")
