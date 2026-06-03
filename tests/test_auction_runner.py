"""Tests for the auction sniper control logic (fake IO + fake clock; no game).

OCR constants are the REAL strings captured from the live buy-out flow (zh-Hans)."""
from v4.auction_runner import (
    BID_CONFIRM,
    BUYOUT_CONFIRM,
    DETAIL,
    HOUSE,
    RESULTS,
    SEARCH,
    AuctionSniper,
    classify_auction_screen,
)

HOUSE_OCR = "拍卖场 | 搜索拍卖 | 开始拍卖 | 我的竞价 | 拍卖提醒"
SEARCH_OCR = "搜寻 | 车厂 | 型号 | 最高买断价 | 确认 | 返回"
RESULTS_OCR = "拍卖场 | 拍卖详情 | PORTOFINO | 2018 法拉利 | 已拥有 | 32,000 | 240,000 | 4 分钟 | 中标者 | 卖家"
# SS3: single-listing detail (车辆详情 pager + car stats + 竞价/买断 action rows).
DETAIL_OCR = "拍卖详情 | 车辆详情 | PORTOFINO '18 | 2018 法拉利 | 史诗 | S1 714 | 传动系统 后轮驱动 | 马力 441 千瓦 | 扭矩 760 牛米 | 3 分钟 | 竞价 36,000 | 买断 240,000"
# SS5: the buy-out confirm (the ONLY dialog the snipe may confirm).
CONFIRM_OCR = "买断 | 是否确定要买断该拍卖？ | 嗯 | 不"
# SS4: the BID confirm -- the danger screen the snipe must refuse.
BID_OCR = "竞价 | 是否确定要为该拍卖竞价 CR 36,000？ | 如果有人出价高于您，您可以立即从“我的竞价”取回点数。 | 嗯 | 不"
NETWORK_OCR = "注意！ | 连接已断开，请稍后再试 | 返回漫游模式才可接受邀请"


def test_classify_auction_screen():
    assert classify_auction_screen(SEARCH_OCR) == SEARCH
    assert classify_auction_screen(RESULTS_OCR) == RESULTS
    assert classify_auction_screen(DETAIL_OCR) == DETAIL
    assert classify_auction_screen(HOUSE_OCR) == HOUSE
    assert classify_auction_screen(CONFIRM_OCR) == BUYOUT_CONFIRM
    assert classify_auction_screen(BID_OCR) == BID_CONFIRM
    assert classify_auction_screen("我的车辆 | 斯巴鲁") == "unknown"


def test_buyout_and_bid_confirms_are_distinct():
    # The two confirm dialogs must never be confused -- one buys, one bids.
    assert classify_auction_screen(CONFIRM_OCR) == BUYOUT_CONFIRM
    assert classify_auction_screen(BID_OCR) == BID_CONFIRM
    # The search screen (carries 最高买断价 + 确认) must NOT read as a buy-out confirm.
    assert classify_auction_screen(SEARCH_OCR) == SEARCH


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)


class FakeIO:
    """Scripts the snipe flow: SEARCH --enter--> RESULTS --select_buyout--> BUYOUT_CONFIRM."""

    def __init__(
        self,
        *,
        focused=True,
        has_listing=True,
        confirm_shows=True,
        outcome="bought",
        confirm_screen=BUYOUT_CONFIRM,
        start_state=SEARCH,
        blocked=False,
    ):
        self._blocked = blocked
        self.presses = []
        self.calls = []
        self._focused = focused
        self._has_listing = has_listing
        self._confirm_shows = confirm_shows
        self._outcome = outcome
        self._confirm_screen = confirm_screen   # what select_buyout lands on (buyout vs BID)
        self._state = start_state
        self.run_search_count = 0
        self.activate_calls = 0

    def focused(self):
        return self._focused

    def activate(self):
        self.activate_calls += 1
        self._focused = True   # simulate the foreground switch succeeding

    def screen(self):
        return self._state

    def press(self, btn):
        self.presses.append(btn)
        if btn == "enter" and self._state == HOUSE:
            self._state = SEARCH        # 拍卖场 landing: 搜索拍卖 -> 搜寻
        elif btn == "enter" and self._state == SEARCH:
            self._state = RESULTS
        elif btn == "esc":
            self._state = HOUSE         # results/back -> 拍卖场 landing

    def run_search(self):
        # fire a fresh query from the 搜寻 config -> results (the re-search step)
        self.run_search_count += 1
        self._state = RESULTS

    def blocked(self):
        return self._blocked

    def has_listing(self):
        return self._has_listing

    def open_buyout(self):
        self.calls.append("open_buyout")
        return True

    def select_buyout(self, delay):
        self.calls.append("select_buyout")
        self.presses.append("down")
        if self._confirm_shows:
            self._state = self._confirm_screen

    def confirm_buyout(self):
        self.calls.append("confirm_buyout")
        return self._outcome

    def collect(self):
        self.calls.append("collect")


def _sniper(io, **kw):
    clk = Clock()
    return AuctionSniper(io, clock=clk.now, sleeper=clk.sleep, **kw)


def test_dry_run_stops_at_detail_never_buys():
    # Dry-run reaches 车辆详情 (open_buyout) and backs out with B; it never opens the
    # confirm dialog (which ignores B), so it's zero-risk and never selects/buys.
    io = FakeIO()
    s = _sniper(io, dry_run=True, max_cars=3)
    assert s.run() == "dry_done"
    assert "open_buyout" in io.calls          # reached the detail screen
    assert "select_buyout" not in io.calls    # did NOT press down / open the confirm
    assert "confirm_buyout" not in io.calls   # never bought
    assert "down" not in io.presses           # no buy-out select in dry-run
    assert "esc" in io.presses                # backed out (B works on the detail screen)


def test_real_run_buys_and_collects():
    io = FakeIO(outcome="bought")
    s = _sniper(io, dry_run=False, max_cars=1)
    assert s.run() == "max_cars"
    assert s.bought == 1
    assert io.calls == ["open_buyout", "select_buyout", "confirm_buyout", "collect"]


def test_auto_focus_brings_game_forward_then_runs():
    # Forza not foreground at start -> with auto_focus the snipe re-focuses it and proceeds,
    # instead of sitting paused (the "不会动" bug when the GUI/another window was on top).
    io = FakeIO(focused=False, outcome="bought")
    s = _sniper(io, dry_run=False, max_cars=1, auto_focus=True)
    assert s.run() == "max_cars"
    assert io.activate_calls >= 1
    assert s.bought == 1


def test_no_auto_focus_pauses_when_unfocused():
    io = FakeIO(focused=False)
    s = _sniper(io, dry_run=False, max_cars=1, max_minutes=0.02, auto_focus=False)
    s.run()
    assert io.activate_calls == 0
    assert s.bought == 0


def test_buys_a_listing_already_up():
    # A buyable listing already on the results page is taken immediately (validated path /
    # the instant a snipe lands) -- no extra re-search round-trip needed.
    io = FakeIO(start_state=RESULTS, outcome="bought")
    s = _sniper(io, dry_run=False, max_cars=1)
    assert s.run() == "max_cars"
    assert s.bought == 1
    assert io.calls == ["open_buyout", "select_buyout", "confirm_buyout", "collect"]


def test_server_unavailable_waits_without_navigating():
    # 拍卖服务器/网络不可用 (服务器目前无法使用 / 请稍后再试) -> just wait + re-read; never press
    # into a dead screen (and never wander).
    io = FakeIO(blocked=True)
    s = _sniper(io, dry_run=False, max_cars=1, max_minutes=0.02)
    s.run()
    assert s.bought == 0
    assert io.calls == []
    assert "esc" not in io.presses and "enter" not in io.presses


def test_re_searches_from_landing_not_idle():
    # On the 拍卖场 landing (where it used to sit idle): enter 搜索拍卖 -> 搜寻 -> 确认 ->
    # results -> buy. It must actively re-search from the landing, never just sit there.
    io = FakeIO(start_state=HOUSE, outcome="bought")
    s = _sniper(io, dry_run=False, max_cars=1)
    assert s.run() == "max_cars"
    assert s.bought == 1
    assert io.run_search_count >= 1


def test_re_searches_while_results_empty():
    # Research: the results list does NOT auto-refresh. While no buyable listing is up, re-fire
    # the query every cycle (the snipe loop waiting for the target), never park on a stale list.
    io = FakeIO(start_state=RESULTS, has_listing=False)
    s = _sniper(io, dry_run=False, max_cars=1, max_minutes=0.02)
    s.run()
    assert io.run_search_count >= 1           # re-searched while empty
    assert s.bought == 0


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


def test_starting_on_buyout_confirm_buys_in_real_run():
    # A prior attempt left the 买断 confirm open (B can't dismiss it). In a real run we
    # complete it (A on 嗯) rather than getting stuck.
    io = FakeIO(start_state=BUYOUT_CONFIRM, outcome="bought")
    s = _sniper(io, dry_run=False, max_cars=1)
    assert s.run_once() == "bought"
    assert io.calls == ["confirm_buyout", "collect"]


def test_starting_on_buyout_confirm_dryrun_does_not_buy():
    io = FakeIO(start_state=BUYOUT_CONFIRM)
    s = _sniper(io, dry_run=True, max_cars=1)
    assert s.run_once() == "dry_seen"
    assert "confirm_buyout" not in io.calls


def test_starting_on_bid_confirm_is_never_touched():
    # B can't dismiss it and Down+A risks bidding -> refuse to touch; user backs out manually.
    io = FakeIO(start_state=BID_CONFIRM)
    s = _sniper(io, dry_run=False, max_cars=1)
    assert s.run_once() == "recovered"
    assert io.calls == []
    assert io.presses == []


def test_bid_confirm_aborts_without_buying():
    # If the Down drops and select lands on the BID confirm, the snipe must back out and
    # NEVER confirm -- even in a real (non-dry) run that otherwise would buy.
    io = FakeIO(confirm_screen=BID_CONFIRM)
    s = _sniper(io, dry_run=False, max_cars=1)
    assert s.run_once() == "recovered"
    assert "confirm_buyout" not in io.calls   # never confirm a bid
    assert "collect" not in io.calls
    assert s.bought == 0


def test_real_run_aborting_on_bid_never_buys_in_loop():
    # Across the whole loop, a persistent BID-confirm landing buys nothing (bounded by time).
    io = FakeIO(confirm_screen=BID_CONFIRM)
    s = _sniper(io, dry_run=False, max_cars=1, max_minutes=0.01)
    assert s.run() in ("max_minutes", "stopped")
    assert s.bought == 0
    assert "confirm_buyout" not in io.calls
