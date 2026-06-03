"""Tests for the buy-car event-driven post-tap settle (pure frame-diff decision; no game)."""
import numpy as np

from buy_car_runner import BuyCarRunner


def _f(val, shape=(36, 80)):
    return np.full(shape, float(val), dtype="float32")


def test_frame_diff_basics():
    assert BuyCarRunner._frame_diff(_f(10), _f(10)) == 0.0
    assert BuyCarRunner._frame_diff(_f(0), _f(50)) == 50.0
    assert BuyCarRunner._frame_diff(_f(0), None) >= 999.0          # missing frame -> "changed"
    assert BuyCarRunner._frame_diff(_f(0, (10, 10)), _f(0, (5, 5))) >= 999.0  # shape mismatch


def _settle_index(frames, change=6.0, stable=2.0, need=2):
    """Drive _settle_step over frames[0]=pre, frames[1:]=polls; return the 1-based poll index
    it would settle at, or None (= would wait the cap). Mirrors the live loop's decision."""
    pre = frames[0]
    last = pre
    changed = False
    st = 0
    for i, cur in enumerate(frames[1:], start=1):
        changed, st, _ = BuyCarRunner._settle_step(pre, last, cur, changed, st, change, stable)
        if changed and st >= need:
            return i
        last = cur
    return None


def test_settle_returns_after_change_then_stable():
    # pre=0 -> transition to 100 -> holds stable: settles once 2 stable frames follow the change
    assert _settle_index([_f(0), _f(100), _f(100), _f(100)]) == 3


def test_settle_waits_when_screen_never_changes():
    # never differs from the pre-tap frame -> never "changed" -> wait the cap (None)
    assert _settle_index([_f(50)] * 6) is None


def test_settle_waits_on_animated_screen():
    # changed, but keeps moving (rotating car) -> never stabilises -> wait the cap (None)
    assert _settle_index([_f(0), _f(100), _f(80), _f(110), _f(70), _f(120)]) is None


def test_settle_needs_the_change_first():
    # stable from the start but identical to pre (no change) must NOT settle early
    assert _settle_index([_f(40), _f(40), _f(40), _f(40)]) is None
