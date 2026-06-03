"""Tests for the auction sniper control logic (fake IO + fake clock; no game)."""
from v4.auction_runner import (
    BUYOUT_CONFIRM,
    HOUSE,
    RESULTS,
    SEARCH,
    AuctionSniper,
    classify_auction_screen,
)

HOUSE_OCR = "拍卖场 | 搜索拍卖 | 开始拍卖 | 我的竞价 | 拍卖提醒"
SEARCH_OCR = "搜寻 | 车厂 | 型号 | 最高买断价 | 确认 | 返回"
RESULTS_OCR = "拍卖场 | 拍卖详情 | 即将结束 | 拍卖选项 | REVUELTO | 183,000"
CONFIRM_OCR = "买断 | 确定要买断吗？ | 是 | 否"


def test_classify_auction_screen():
    assert classify_auction_screen(SEARCH_OCR) == SEARCH
    assert classify_auction_screen(RESULTS_OCR) == RESULTS
    assert classify_auction_screen(HOUSE_OCR) == HOUSE
    assert classify_auction_screen(CONFIRM_OCR) == BUYOUT_CONFIRM
    assert classify_auction_screen("我的车辆 | 斯巴鲁") == "unknown"


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)


class FakeIO:
    """Scripts the snipe flow: SEARCH --enter--> RESULTS --select_buyout--> BUYOUT_CONFIRM."""

    def __init__(self, *, focused=True, has_listing=True, confirm_shows=True, outcome="bought"):
        self.presses = []
        self.calls = []
        self._focused = focused
        self._has_listing = has_listing
        self._confirm_shows = confirm_shows
        self._outcome = outcome
        self._state = SEARCH

    def focused(self):
        return self._focused

    def screen(self):
        return self._state

    def press(self, btn):
        self.presses.append(btn)
        if btn == "enter" and self._state == SEARCH:
            self._state = RESULTS
        elif btn == "esc":
            self._state = SEARCH

    def has_listing(self):
        return self._has_listing

    def open_buyout(self):
        self.calls.append("open_buyout")
        return True

    def select_buyout(self, delay):
        self.calls.append("select_buyout")
        self.presses.append("down")
        if self._confirm_shows:
            self._state = BUYOUT_CONFIRM

    def confirm_buyout(self):
        self.calls.append("confirm_buyout")
        return self._outcome

    def collect(self):
        self.calls.append("collect")


def _sniper(io, **kw):
    clk = Clock()
    return AuctionSniper(io, clock=clk.now, sleeper=clk.sleep, **kw)


def test_dry_run_sees_confirm_but_never_buys():
    io = FakeIO()
    s = _sniper(io, dry_run=True, max_cars=3)
    assert s.run() == "dry_done"
    assert "confirm_buyout" not in io.calls   # dry-run must NOT confirm a purchase
    assert "esc" in io.presses                # it backs out after seeing the confirm
    assert "down" in io.presses               # the buy-out select was pressed once
    assert io.presses.count("down") == 1      # ...and only once (never bid)


def test_real_run_buys_and_collects():
    io = FakeIO(outcome="bought")
    s = _sniper(io, dry_run=False, max_cars=1)
    assert s.run() == "max_cars"
    assert s.bought == 1
    assert io.calls == ["open_buyout", "select_buyout", "confirm_buyout", "collect"]


def test_empty_results_is_no_cars_not_a_buy():
    io = FakeIO(has_listing=False)
    s = _sniper(io, dry_run=False, max_cars=1)
    assert s.run_once() == "no_cars"
    assert "open_buyout" not in io.calls


def test_confirm_not_seen_bails_without_buying():
    io = FakeIO(confirm_shows=False)
    s = _sniper(io, dry_run=False, max_cars=1)
    assert s.run_once() in ("recovered", "no_cars")
    assert "confirm_buyout" not in io.calls    # never confirm if the buy-out dialog isn't verified


def test_stop_event_halts():
    import threading
    stop = threading.Event()
    stop.set()
    io = FakeIO()
    s = _sniper(io, dry_run=False, max_cars=5, stop_event=stop)
    assert s.run() == "stopped"
    assert io.calls == []
