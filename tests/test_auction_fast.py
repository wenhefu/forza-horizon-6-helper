"""Tests for the AuctionIO speed levers: the fast Y buy-out path (with safe fallback to the
validated detail path) and the recognize-on-change OCR skip.

The safety invariant -- a snipe NEVER places a bid -- is preserved: the fast quick-menu path
only presses Enter when 买断 is the confirmed focus (else it backs out without Enter), and the
sniper's confirm gate (tested in test_auction_runner) aborts on the BID dialog regardless."""
import numpy as np

from v4.auction_runner import (
    AuctionIO,
    DETAIL,
    OPTIONS,
    RESULTS,
    classify_auction_screen,
)


class _Item:
    def __init__(self, text):
        self.text = text


class _V3:
    def __init__(self, selected=""):
        self.selected_item = selected


class _Snap:
    def __init__(self, texts, selected=""):
        self.ocr_items = [_Item(t) for t in texts]
        self.v3 = _V3(selected)


class FakeRec:
    """Returns a scripted (ocr_texts, selected_item) per capture(); repeats the last forever."""
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.captures = 0

    def capture(self, **kw):
        item = self._scripted[min(self.captures, len(self._scripted) - 1)]
        self.captures += 1
        return _Snap(item[0], item[1])


class FakePad:
    def __init__(self):
        self.taps = []

    def tap(self, name, hold=0.1):
        self.taps.append(name)


def _io(scripted, **kw):
    return AuctionIO(FakeRec(scripted), FakePad(), sleep=lambda s: None, **kw)


OPT = (["竞价", "买断"], "竞价")                                  # Y quick-menu, 竞价 focused
OPT_BUYOUT = (["竞价", "买断"], "买断")                           # Y quick-menu, 买断 focused
DETAIL_SNAP = (["车辆详情", "竞价", "买断", "马力", "扭矩"], "竞价")  # the 车辆详情 stat page
RESULTS_SNAP = (["拍卖详情", "240,000"], "")                      # the results list


def test_classify_recognizes_y_quickmenu_as_options():
    assert classify_auction_screen("竞价 | 买断 | 关注") == OPTIONS
    # the detail page (with stats) is distinct from the quick-menu
    assert classify_auction_screen("车辆详情 | 竞价 | 买断 | 马力") == DETAIL


def test_open_buyout_fast_uses_y_and_reaches_quickmenu():
    io = _io([OPT], fast_buyout=True)
    assert io.open_buyout() is True
    assert "y" in io.pad.taps         # opened via the Y quick-menu (fast), not 选择/Enter
    assert "a" not in io.pad.taps     # open only -- no select/confirm happens here


def test_open_buyout_fast_falls_back_to_enter_when_menu_unrecognized():
    # 6 fast looks never show an action screen -> close (B) -> back on results -> Enter -> detail.
    io = _io([RESULTS_SNAP] * 7 + [DETAIL_SNAP], fast_buyout=True)
    assert io.open_buyout() is True
    assert "y" in io.pad.taps         # tried the fast menu
    assert "b" in io.pad.taps         # closed the unrecognized menu
    assert "a" in io.pad.taps         # fell back to 选择/Enter -> 车辆详情


def test_validated_open_buyout_uses_enter_not_y_when_fast_off():
    io = _io([DETAIL_SNAP])           # fast_buyout defaults off
    assert io.open_buyout() is True
    assert "y" not in io.pad.taps     # never touches Y on the validated path
    assert "a" in io.pad.taps         # 选择/Enter


def test_select_buyout_on_quickmenu_enters_only_when_buyout_focused():
    io = _io([OPT_BUYOUT], fast_buyout=True)
    io.select_buyout(0.0)
    assert "a" in io.pad.taps         # 买断 focused -> Enter opens ITS confirm


def test_select_buyout_on_quickmenu_aborts_without_enter_if_buyout_never_focused():
    # SAFETY: 竞价 stays focused -> NEVER press Enter (that would bid); back out via B instead.
    io = _io([OPT], fast_buyout=True)
    io.select_buyout(0.0)
    assert "a" not in io.pad.taps     # never confirmed -> a bid is never opened
    assert "b" in io.pad.taps         # aborted


def test_select_buyout_on_detail_is_validated_down_then_enter():
    io = _io([DETAIL_SNAP])
    io.select_buyout(0.0)
    assert io.pad.taps == ["dpad_down", "a"]   # ONE Down (竞价 -> 买断) then Enter


def test_recognize_on_change_skips_ocr_when_frame_unchanged(monkeypatch):
    io = _io([RESULTS_SNAP], recognize_on_change=True)
    same = np.zeros((8, 8), dtype="float32")
    monkeypatch.setattr(io, "_cheap_gray", lambda: same)
    assert io.screen() == RESULTS         # first call must OCR
    assert io.recognizer.captures == 1
    assert io.screen() == RESULTS         # frame unchanged -> reuse cached tag, no OCR
    assert io.recognizer.captures == 1    # capture count did NOT increase


def test_recognize_on_change_off_always_ocrs():
    io = _io([RESULTS_SNAP], recognize_on_change=False)
    io.screen()
    io.screen()
    assert io.recognizer.captures == 2    # every screen() re-OCRs when the lever is off
