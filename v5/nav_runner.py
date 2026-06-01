"""V5 event-driven navigation runner (phase 3b wiring).

Wires the three V5 engines into something runnable:
  recognize = V4Recognizer(capture_engine=CaptureEngine)  (continuous dxcam frames)
            + occlusion fallback (dxcam screen=="unknown" -> synchronous PrintWindow)
  decide    = v5.screen_registry.next_button(understanding, goal)
  press     = Gamepad.tap
driven by v5.reactor.EventReactor (press -> watch -> react, no fixed sleeps).

Same safety boundary as V1-V4: read-only capture + ViGEmBus input only; the game
must be in the foreground (no fake-focus). It NEVER presses unless you run it.

This is the experimental V5 navigation demo to live-test the felt latency; it
navigates the current screen to a goal (default the EventLab race-start menu) and
hands back. The full mode-three (buy + farm) stays on the proven V4 path.
"""
from __future__ import annotations

import logging
import threading
from types import SimpleNamespace

import focus
from gamepad import BUTTON_NAMES, Gamepad
from v4.recognizer import V4Recognizer
from v5.capture_engine import CaptureEngine
from v5.reactor import EventReactor
from v5.screen_registry import next_button


def _background_understanding() -> SimpleNamespace:
    # Sentinel for "game not in foreground" -> next_button(spec=None) -> wait.
    return SimpleNamespace(
        screen="background", selected_item="", active_tab="",
        filter_state={}, scroll_state={}, ocr_regions=[],
    )


class V5Navigator:
    def __init__(
        self,
        title: str = "Forza",
        goal: str = "race_menu",
        on_log=None,
        logger=None,
        require_foreground: bool = True,
        use_capture_engine: bool = True,
        step_timeout: float = 2.5,
        stall_seconds: float = 30.0,
        max_seconds: float = 600.0,
        recognizer=None,
        pad=None,
        engine=None,
    ):
        self.title = title
        self.goal = goal
        self.on_log = on_log or (lambda message: None)
        self.logger = logger or logging.getLogger("forza6helper.v5.nav")
        self.require_foreground = require_foreground
        self.step_timeout = step_timeout
        self.stall_seconds = stall_seconds
        self.max_seconds = max_seconds
        if engine is not None:
            self.engine = engine
        else:
            self.engine = CaptureEngine(title, logger=self.logger) if use_capture_engine else None
        if recognizer is not None:
            self.recognizer = recognizer
        else:
            self.recognizer = V4Recognizer(title=title, capture_engine=self.engine, logger=self.logger)
        self._pad = pad
        self._stop = threading.Event()
        self.fallbacks = 0  # how many times dxcam unknown -> synchronous re-grab

    # -- wiring ------------------------------------------------------------
    def _get_pad(self):
        if self._pad is None:
            self._pad = Gamepad(logger=self.logger)
        return self._pad

    def recognize(self):
        if self.require_foreground and not focus.is_foreground(self.title):
            return _background_understanding()
        snap = self.recognizer.capture(full_ocr=False, region_ocr=True)
        if getattr(snap, "capture_method", "") == "dxcam" and str(snap.v3.screen) == "unknown":
            # dxcam captures on-screen pixels; an overlapping window reads as unknown.
            # Re-grab synchronously (PrintWindow renders the window's own content).
            self.fallbacks += 1
            snap = self.recognizer.capture(full_ocr=False, region_ocr=True, max_age_ms=0.0)
        return snap.v3

    def decide(self, understanding):
        return next_button(understanding, self.goal)

    def press(self, button: str) -> None:
        if button not in BUTTON_NAMES:
            self.on_log(f"V5 导航：忽略未知按键 {button!r}。")
            return
        self._get_pad().tap(button, hold=0.12)

    # -- run ---------------------------------------------------------------
    def run(self):
        self.on_log(f"V5 事件驱动导航启动：目标={self.goal}，引擎={'dxcam' if self.engine else 'off'}。")
        if self.engine is not None:
            started = self.engine.start()
            self.on_log("抓帧引擎：" + ("dxcam 已启动（连续抓帧）。" if started else "dxcam 不可用，回退同步抓图。"))
        try:
            reactor = EventReactor(
                self.recognize, self.decide, self.press,
                on_log=self.on_log, step_timeout=self.step_timeout,
                stall_seconds=self.stall_seconds, stop_event=self._stop,
            )
            result = reactor.run(max_seconds=self.max_seconds)
            self.on_log(
                f"V5 导航结束：reason={result.reason} 步数={result.steps} "
                f"用时={result.elapsed_s:.1f}s 最后画面={result.last_screen} 遮挡回退={self.fallbacks} 次。"
            )
            return result
        finally:
            if self._pad is not None:
                try:
                    self._pad.neutral()
                except Exception:
                    pass
            if self.engine is not None:
                self.engine.stop()

    def stop(self):
        self._stop.set()
