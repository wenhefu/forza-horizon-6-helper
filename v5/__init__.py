"""V5 — experimental continuous-monitoring + Forza UI knowledge layer.

This package is additive and OPT-IN; it does not change the stable V4 behavior.
It stays inside the same safety boundary as V1-V4:

- no game-process injection
- no API hooking
- no KeepActive / fake-focus
- no game-file modification
- screen capture is read-only; input is only the ViGEmBus virtual Xbox pad

Phase 1 (foundation):
- ``capture_engine``: a background dxcam capture thread that feeds the existing
  stateless V3/V4 recognizer the latest frame (with graceful fallback to the V4
  GDI/PrintWindow capture when dxcam is unavailable).
- ``screen_registry``: a declarative model of the Forza UI built on ``v3.ui_tree``
  plus a generic route planner (the base for "the program understands Forza").
"""

__all__ = ["capture_engine", "screen_registry"]
