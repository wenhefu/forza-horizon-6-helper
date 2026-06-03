"""Tests for AuctionIO.confirm_buyout (dropped-yes re-press + outcome), with fake rec/pad."""
import threading

from v4.auction_runner import AuctionIO


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
    """Returns a scripted sequence of (ocr_texts, selected_item) per capture()."""
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self._i = 0

    def capture(self, **kw):
        item = self._scripted[min(self._i, len(self._scripted) - 1)]
        self._i += 1
        return _Snap(item[0], item[1])


class FakePad:
    def __init__(self):
        self.taps = []

    def tap(self, name, hold=0.1):
        self.taps.append(name)


def _io(scripted, **kw):
    return AuctionIO(FakeRec(scripted), FakePad(), sleep=lambda s: None, **kw)


CONFIRM = (["买断", "是否确定要买断该拍卖", "嗯", "不"], "")
SUCCESS = (["买断成功", "您可以在“我的竞价”页面领取该车辆", "确定"], "买断成功")


def test_confirm_buyout_re_presses_on_dropped_yes():
    # 嗯 dropped: the 买断 confirm is still showing for two reads, then 买断成功 appears.
    io = _io([CONFIRM, CONFIRM, SUCCESS])
    assert io.confirm_buyout() == "bought"
    assert io.pad.taps.count("a") >= 2   # initial 嗯 + at least one re-press


def test_confirm_buyout_success_first_read():
    io = _io([SUCCESS])
    assert io.confirm_buyout() == "bought"


def test_confirm_buyout_failed_marker():
    io = _io([(["买断", "已售出"], "")])
    assert io.confirm_buyout() == "failed"


def test_confirm_buyout_stops_on_stop_event():
    stop = threading.Event()
    stop.set()
    io = _io([CONFIRM], stop_event=stop)
    assert io.confirm_buyout() == "stopped"
