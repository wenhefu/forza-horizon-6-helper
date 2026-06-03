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
import re
import time

from v3.buying_ui import (
    detect_auction_detail,
    detect_auction_house,
    detect_auction_results,
    detect_auction_search,
    detect_bid_confirm,
    detect_buyout_confirm,
    detect_network_warning,
)

# A thousands-separated CR price (240,000 / 32,000) -- present on real listings, absent on
# the blank/loading results screen. Used to tell "has listings" from "still loading".
_PRICE_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
# The buy-out price specifically (for logging what a snipe is about to grab).
_BUYOUT_PRICE_RE = re.compile(r"买断[^\d]{0,8}(\d{1,3}(?:,\d{3})+)")

# Screen tags the sniper reasons about.
SEARCH = "search"
RESULTS = "results"
DETAIL = "detail"
HOUSE = "house"
BUYOUT_CONFIRM = "buyout_confirm"
BID_CONFIRM = "bid_confirm"
UNKNOWN = "unknown"


def classify_auction_screen(ocr_text: str) -> str:
    """Map OCR text to one auction screen tag.

    Priority (most-specific first): buy-out confirm > BID confirm > single-listing detail >
    results list > search > house. The two confirm dialogs are checked first and kept
    distinct so the snipe can recognise -- and refuse -- the BID dialog; detail is checked
    before results because both carry '拍卖详情' (detail adds the 车辆详情 pager + car stats)."""
    if detect_buyout_confirm(ocr_text)["visible"]:
        return BUYOUT_CONFIRM
    if detect_bid_confirm(ocr_text)["visible"]:
        return BID_CONFIRM
    if detect_auction_detail(ocr_text)["visible"]:
        return DETAIL
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

    def _esc_toward_search(self) -> bool:
        """Press B (返回, never confirms) up to a few times until the 搜寻 screen appears.
        From a confirm/detail screen the search is 2-3 backs away, so one ESC isn't enough."""
        if self.io.screen() == SEARCH:
            return True
        for _ in range(4):
            self.io.press("esc")
            if self._wait_for({SEARCH}, 1.5) == SEARCH:
                return True
        return self.io.screen() == SEARCH

    def run_once(self) -> str:
        """One snipe attempt. Returns: bought | no_cars | dry_seen | recovered | failed."""
        if not self.io.focused():
            return "recovered"
        if not self._esc_toward_search():
            return "recovered"
        # run the (pre-set) search
        self.io.press("enter")
        if self._wait_for({RESULTS}, 6.0) != RESULTS:
            return "no_cars"
        if not self.io.has_listing():
            self.io.press("esc")  # empty/loading/disconnected results -> back out, re-search
            return "no_cars"
        return self._buy_out_first()

    def _buy_out_first(self) -> str:
        """Buy out the first listing via the captured flow:
        选择/Enter -> 车辆详情 (竞价 focused, 买断 below) -> Down ONCE -> Enter -> 买断 confirm.

        SAFETY: the confirm is verified to be the BUY-OUT dialog before the final yes. If the
        Down dropped and we land on the BID (竞价) confirm instead, we detect it and back out
        WITHOUT confirming -- a snipe must never place a bid."""
        if not self.io.open_buyout():           # Enter (选择) -> 车辆详情 with 竞价/买断 rows
            self.io.press("esc")
            return "recovered"
        # select 买断: ONE down (竞价 -> 买断), never retried, then open its confirm dialog.
        self.io.select_buyout(self.buyout_select_delay)
        s = self._wait_for({BUYOUT_CONFIRM, BID_CONFIRM}, 2.5)
        if s == BID_CONFIRM:
            # The Down didn't land on 买断 -> this is the BID dialog. NEVER confirm. Back out.
            self.io.press("esc")
            self.on_log("抢车：出现『竞价』确认框(非买断),已安全退出,未出价。")
            return "recovered"
        if s != BUYOUT_CONFIRM:
            self.io.press("esc")               # not verified as buy-out -> bail, never confirm
            return "recovered"
        if self.dry_run:
            self.io.press("esc")               # dry-run: saw the buy-out confirm, do NOT buy
            self.on_log("抢车[空跑]：已识别到『买断』确认框,未购买(空跑)。")
            return "dry_seen"
        outcome = self.io.confirm_buyout()      # press 嗯, observe success/failed
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


class AuctionIO:
    """Real game-facing IO for :class:`AuctionSniper`: OUR recognizer (OCR ->
    classify_auction_screen) for sensing + the virtual gamepad for input -- foreground-only,
    read-only capture, no injection. Mirrors the proven sell-runner IO (full-res OCR,
    jittered taps, focus-gated).

    Footer mapping captured live: ``Enter 选择`` = A, ``Esc 返回`` = B, ``Y 拍卖选项`` = Y,
    Down = dpad_down. Both confirm dialogs default-focus 嗯 (yes), so a verified buy-out is
    committed with a single A.

    The CONTROL logic (when to confirm, the BID-confirm abort, ESC-only recovery) lives in
    AuctionSniper and is unit-tested with a fake IO; this class only performs the captured
    key presses + reads the screen. Outcome detection in :meth:`confirm_buyout` is the one
    piece to refine against real post-purchase frames (the dry-run never calls it)."""

    _BTN = {
        "enter": "a", "a": "a",
        "esc": "b", "b": "b",
        "y": "y",
        "down": "dpad_down", "up": "dpad_up",
        "left": "dpad_left", "right": "dpad_right",
    }

    def __init__(
        self,
        recognizer,
        pad,
        *,
        title: str = "Forza",
        on_log=None,
        sleep=time.sleep,
        tap_hold: float = 0.12,
        settle: float = 0.55,
    ):
        self.recognizer = recognizer
        self.pad = pad
        self.title = title
        self.on_log = on_log or (lambda m: None)
        self._sleep = sleep
        self.tap_hold = tap_hold
        self.settle = settle
        self._last_text = ""

    # --- sensing (full-res OCR, mirrors the stable sell runner) ---------------
    def _look(self) -> str:
        snap = self.recognizer.capture(full_ocr=True, region_ocr=True)
        self._last_text = " | ".join(str(getattr(it, "text", "")) for it in snap.ocr_items)
        return self._last_text

    def focused(self) -> bool:
        try:
            import focus
            return focus.is_foreground(self.title)
        except Exception:
            return True

    def screen(self) -> str:
        return classify_auction_screen(self._look())

    # --- input (jittered, anti-pattern timing learned from the OSS sniper) ----
    def press(self, name: str) -> None:
        from gamepad import BUTTON_NAMES
        btn = self._BTN.get(name, name)
        if btn in BUTTON_NAMES:
            self.pad.tap(btn, hold=self.tap_hold)
        self._sleep(self.settle + random.uniform(0.0, 0.12))

    def has_listing(self) -> bool:
        """True only when the results LIST shows a real, buyable listing -- i.e. a
        thousands-separated CR price is present and we are NOT disconnected. The blank/
        loading results screen has empty cards (no prices); a disconnect banner means buys
        would fail."""
        text = self._look()
        if detect_network_warning(text)["visible"]:
            self.on_log("抢车：检测到『连接已断开』,暂不可买,等待重连。")
            return False
        if not detect_auction_results(text)["visible"]:
            return False
        return bool(_PRICE_RE.search(text))

    # --- the captured buy-out flow -------------------------------------------
    def open_buyout(self) -> bool:
        """选择/Enter on the focused results card -> 车辆详情 (竞价 focused, 买断 below)."""
        self.press("enter")
        for _ in range(8):
            if classify_auction_screen(self._look()) == DETAIL:
                m = _BUYOUT_PRICE_RE.search(self._last_text)
                if m:
                    self.on_log(f"抢车：目标买断价 CR {m.group(1)}。")
                return True
        return classify_auction_screen(self._last_text) == DETAIL

    def select_buyout(self, delay: float) -> None:
        """ONE Down (竞价 -> 买断), a settle so it registers, then Enter to open the confirm.
        Exactly one dpad_down, never retried: a retried Down could overshoot back onto 竞价."""
        self.press("down")
        self._sleep(max(0.0, float(delay)))
        self.press("enter")

    def confirm_buyout(self) -> str:
        """Press 嗯 (default-focused) on the ALREADY-VERIFIED 买断 dialog, then read the
        outcome. REFINE-LIVE: success/failure strings nailed against real post-buy frames."""
        self.press("enter")
        self._sleep(0.4)
        info = detect_buyout_confirm(self._look())
        if info["failed"]:
            return "failed"
        if not info["visible"]:
            return "bought"   # dialog gone, no failure marker -> purchased
        return "failed"       # still showing a confirm shape -> uncertain; never re-press

    def collect(self) -> None:
        """No wheelspin on an auction buy -- just settle back to a re-searchable screen."""
        for _ in range(20):
            if classify_auction_screen(self._look()) in (RESULTS, SEARCH, HOUSE, DETAIL):
                return
            self._sleep(0.1)
        self.press("esc")
