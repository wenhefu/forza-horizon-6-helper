"""Event-driven reaction loop for V5 (phase 3a core).

Replaces the V4 cadence "press -> fixed sleep (0.85-1.15s) -> recognize" with
"press -> WATCH the frame stream -> react the instant the state changes (or a
per-step timeout)". Removing the fixed settle sleeps means a menu transition is
handled as fast as the game actually transitions, not after a worst-case wait.

Generic + fully injectable (recognize / decide / press / clock) so it is unit
testable without a game and reusable with either ``v5.screen_registry.next_button``
or the proven ``v4.decision.decide_*`` callables -- both return objects with a
``.button`` (raw) and a ``.name``/``.terminal``.

Scope (phase 3a): the navigation/menu pattern, where the fixed-sleep latency
hurts. A decision with an empty button is a wait (loading / focus-scan
unavailable). The continuous throttle-hold of an ACTIVE race is handled by the
farm runner, not this navigation reactor.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from v4.decision import normalize_button, progress_token


@dataclass
class ReactorResult:
    reason: str  # "goal" | "stopped" | "timeout" | "stalled"
    steps: int
    elapsed_s: float
    last_screen: str = ""


def _default_state_token(understanding) -> str:
    return progress_token(understanding)


def _is_done(decision) -> bool:
    return bool(getattr(decision, "terminal", False)) or str(getattr(decision, "name", "")) == "arrived"


class EventReactor:
    """Drive press -> watch-for-change -> decide, with no fixed settle sleeps."""

    def __init__(
        self,
        recognize,
        decide,
        press,
        *,
        state_token=_default_state_token,
        on_log=None,
        step_timeout: float = 2.5,
        poll_interval: float = 0.04,
        stall_seconds: float = 20.0,
        now=time.monotonic,
        sleep=None,
        stop_event=None,
    ):
        # recognize() -> understanding (.screen/.selected_item/.active_tab/...)
        # decide(understanding) -> decision (.button raw, .name, optional .terminal)
        # press(normalized_button) -> None
        self.recognize = recognize
        self.decide = decide
        self.press = press
        self.state_token = state_token
        self.on_log = on_log or (lambda message: None)
        self.step_timeout = float(step_timeout)
        self.poll_interval = float(poll_interval)
        self.stall_seconds = float(stall_seconds)
        self._now = now
        self._sleep = sleep or time.sleep
        self._stop = stop_event

    def _stopped(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    def run(self, max_seconds: float | None = None) -> ReactorResult:
        start = self._now()
        steps = 0
        last_token = object()  # sentinel that never equals a real token
        last_progress = start
        awaiting = None  # token we pressed from; we are waiting for it to change
        awaiting_deadline = 0.0
        last_screen = ""
        while not self._stopped():
            now = self._now()
            if max_seconds is not None and now - start > max_seconds:
                return ReactorResult("timeout", steps, now - start, last_screen)
            understanding = self.recognize()
            last_screen = str(getattr(understanding, "screen", "") or "")
            token = self.state_token(understanding)
            if token != last_token:
                last_token = token
                last_progress = now
            if awaiting is not None:
                if token != awaiting:
                    awaiting = None  # the press landed -> react this tick (the latency win)
                elif now < awaiting_deadline:
                    self._sleep(self.poll_interval)
                    continue  # still waiting for the screen to change; do NOT re-press
                else:
                    awaiting = None  # step timed out -> re-decide / recover

            decision = self.decide(understanding)
            if _is_done(decision):
                return ReactorResult("goal", steps, self._now() - start, last_screen)

            button = normalize_button(getattr(decision, "button", "") or "")
            if not button:
                # wait decision (loading, focus mismatch with no scan direction)
                if now - last_progress > self.stall_seconds:
                    return ReactorResult("stalled", steps, now - start, last_screen)
                self._sleep(self.poll_interval)
                continue

            self.on_log(f"V5 按键 {button}（{getattr(decision, 'name', '')}）")
            self.press(button)
            steps += 1
            awaiting = token
            awaiting_deadline = self._now() + self.step_timeout
        return ReactorResult("stopped", steps, self._now() - start, last_screen)
