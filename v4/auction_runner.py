"""Auction-house sniper (Phase C). DRY-RUN by default.

Modeled on the FH6 OSS sniper's proven control flow (studied, not copied) but using OUR
recognition (the detect_auction_* OCR detectors) + virtual gamepad, foreground-only, no
injection. The USER pre-sets the search filters (型号 + 最高买断价) on the 搜寻 screen; this
loops: 确认 -> watch results -> buy out the first listing -> collect -> re-search.

SAFETY (buy-out, NOT bid): the 'down' that selects 买断 is pressed ONCE and never retried
(a dropped Down would leave a bid option highlighted, so a retried confirm could BID), and
the 买断 confirm is verified (detect_buyout_confirm) before the final yes. ESC-only recovery
never confirms anything. dry_run=True does everything EXCEPT the final confirm.

The IO layer is injectable so the control logic is unit-tested without a game. The exact
buyout-popup navigation (Y -> 拍卖选项 -> 买断 -> confirm) has hooks marked REFINE-LIVE; the
precise screens/strings get nailed once the flow is captured live, then wired into AuctionIO.
"""
from __future__ import annotations

import random
import time

from v3.buying_ui import (
    detect_auction_house,
    detect_auction_results,
    detect_auction_search,
    detect_buyout_confirm,
)

# Screen tags the sniper reasons about.
SEARCH = "search"
RESULTS = "results"
HOUSE = "house"
BUYOUT_CONFIRM = "buyout_confirm"
UNKNOWN = "unknown"


def classify_auction_screen(ocr_text: str) -> str:
    """Map OCR text to one auction screen tag (priority: confirm > results > search > house)."""
    if detect_buyout_confirm(ocr_text)["visible"]:
        return BUYOUT_CONFIRM
    if detect_auction_results(ocr_text)["visible"]:
        return RESULTS
    if detect_auction_search(ocr_text)["visible"]:
        return SEARCH
    if detect_auction_house(ocr_text)["visible"]:
        return HOUSE
    return UNKNOWN


class AuctionSniper:
    """Drives the snipe loop through an injectable IO (screen/focused/press/has_listing)."""

    def __init__(
        self,
        io,
        *,
        dry_run: bool = True,
        max_cars: int = 1,
        max_minutes: float = 180.0,
        buyout_select_delay: float = 0.12,
        on_log=None,
        clock=time.monotonic,
        sleeper=time.sleep,
        stop_event=None,
    ):
        self.io = io
        self.dry_run = dry_run
        self.max_cars = max(1, int(max_cars))
        self.max_minutes = float(max_minutes)
        self.buyout_select_delay = float(buyout_select_delay)
        self.on_log = on_log or (lambda m: None)
        self.clock = clock
        self.sleeper = sleeper
        self._stop = stop_event
        self.bought = 0
        self.searches = 0
        self.started_at = None

    def _stopped(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    def _wait_for(self, tags, timeout: float):
        """Poll until the screen is one of `tags`, or timeout. Time while not focused does
        not count (we pause, never blind-press)."""
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            if self._stopped():
                return None
            if not self.io.focused():
                self.sleeper(0.3)
                deadline += 0.3  # don't let pause eat the budget
                continue
            s = self.io.screen()
            if s in tags:
                return s
            self.sleeper(0.06)
        return None

    def run_once(self) -> str:
        """One snipe attempt. Returns: bought | no_cars | dry_seen | recovered | failed."""
        if not self.io.focused():
            return "recovered"
        s = self.io.screen()
        if s != SEARCH:
            # Not on the search-config screen -> ESC out toward it (ESC never confirms).
            self.io.press("esc")
            if self._wait_for({SEARCH}, 3.0) != SEARCH:
                return "recovered"
        # run the (pre-set) search
        self.io.press("enter")
        if self._wait_for({RESULTS}, 6.0) != RESULTS:
            return "no_cars"
        if not self.io.has_listing():
            self.io.press("esc")  # empty results -> back out, will re-search
            return "no_cars"
        return self._buy_out_first()

    def _buy_out_first(self) -> str:
        """Buy out the first listing. REFINE-LIVE: the exact Y->拍卖选项->买断 nav is wired in
        AuctionIO once captured; here we drive it through io.open_buyout()/io.select_buyout()
        and verify the confirm before committing."""
        if not self.io.open_buyout():           # Y -> 拍卖选项 (and toward 买断)
            self.io.press("esc")
            return "recovered"
        # select 买断: ONE down, never retried, + a settle delay so it registers before confirm
        self.io.select_buyout(self.buyout_select_delay)
        if self._wait_for({BUYOUT_CONFIRM}, 2.0) != BUYOUT_CONFIRM:
            self.io.press("esc")               # not the buy-out confirm -> bail, never confirm
            return "recovered"
        if self.dry_run:
            self.io.press("esc")               # dry-run: saw the confirm, do NOT buy
            self.on_log("抢车[空跑]：已识别到买断确认框,未购买(空跑)。")
            return "dry_seen"
        outcome = self.io.confirm_buyout()      # press yes, observe success/failed
        if outcome == "bought":
            self.io.collect()
            return "bought"
        return "failed"

    def run(self) -> str:
        """Loop until max_cars / max_minutes / stop. Returns the stop reason."""
        self.started_at = self.clock()
        self.on_log(f"抢车{'[空跑]' if self.dry_run else ''}启动：最多 {self.max_cars} 辆 / {self.max_minutes:.0f} 分钟。")
        while not self._stopped():
            if self.bought >= self.max_cars:
                return "max_cars"
            if (self.clock() - self.started_at) / 60.0 >= self.max_minutes:
                return "max_minutes"
            outcome = self.run_once()
            self.searches += 1
            if outcome == "bought":
                self.bought += 1
                self.on_log(f"抢车：已买下 {self.bought} 辆。")
            elif outcome == "dry_seen" and self.dry_run:
                return "dry_done"   # dry-run proves the whole path once; stop
            self.sleeper(0.15 + random.uniform(0.0, 0.1))  # jittered loop pace
        return "stopped"
