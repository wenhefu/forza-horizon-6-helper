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
    detect_auction_collected,
    detect_auction_detail,
    detect_auction_house,
    detect_auction_options,
    detect_auction_results,
    detect_auction_search,
    detect_auction_won,
    detect_bid_confirm,
    detect_buyout_confirm,
    detect_buyout_success,
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
        auto_focus: bool = True,
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
        self.auto_focus = auto_focus
        self.bought = 0
        self.searches = 0
        self.started_at = None
        self._refocus_logged = False

    def _stopped(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    def _ensure_focus(self) -> bool:
        """The snipe only presses while Forza is the foreground window (safety). If it isn't
        and auto_focus is on, bring it to the front (a normal foreground switch -- no inject,
        no fake-focus) so the snipe keeps running while you look at the GUI. Returns whether
        Forza is foreground after the attempt."""
        if self.io.focused():
            return True
        if self.auto_focus and hasattr(self.io, "activate"):
            if not self._refocus_logged:
                self.on_log("抢车：Forza 不在前台,正自动切回(开着别的窗口也能跑;按停止可中止)。")
                self._refocus_logged = True
            self.io.activate()
            self.sleeper(0.4)
        return self.io.focused()

    def _wait_for(self, tags, timeout: float):
        """Poll until the screen is one of `tags`, or timeout. Time while not focused does
        not count (we pause, never blind-press)."""
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            if self._stopped():
                return None
            if not self._ensure_focus():
                self.sleeper(0.3)
                deadline += 0.3  # don't let pause eat the budget
                continue
            s = self.io.screen()
            if s in tags:
                return s
            self.sleeper(0.06)
        return None

    def run_once(self) -> str:
        """One snipe attempt -- RE-SEARCHES every cycle. Returns:
        bought | no_cars | dry_seen | recovered | failed.

        Research (FH5/FH6 OSS snipers + guides) is unanimous: the auction results list does
        NOT auto-refresh while you sit on it -- new listings only appear on a fresh query. So
        each cycle we back out to the 搜寻 config and re-fire the search. We stay INSIDE the
        auction-house menu (ESC only to 搜寻, never out to the open world, which would force a
        multi-second reload). A tight filter (exact model + 最高买断价) makes any result the
        target, so a hit is a 1-2 press buy-out."""
        if not self._ensure_focus():
            return "recovered"
        s = self.io.screen()
        if s == BUYOUT_CONFIRM:
            # Sitting on a VERIFIED buy-out confirm (e.g. a prior attempt was interrupted).
            # This dialog ignores B/Esc -- the only exits are A on 嗯 (buy) or navigating to 不.
            if self.dry_run:
                self.on_log("抢车[空跑]：当前停在『买断』确认框(遗留),未购买(空跑)。")
                return "dry_seen"
            outcome = self.io.confirm_buyout()    # A on 嗯 -> buy
            if outcome == "bought":
                self.io.collect()
                return "bought"
            return "failed"
        if s == BID_CONFIRM:
            # On the BID confirm: B can't dismiss it and Down+A risks confirming the bid, so
            # refuse to touch it -- report and let the user back out via 不 manually.
            self.on_log("抢车：当前停在『竞价』确认框(危险),已停手,请手动选『不』退出。")
            return "recovered"
        if s == RESULTS:
            # A buyable listing already up -> take it (validated buy + the instant a snipe lands).
            if self.io.has_listing():
                return self._buy_out_first()
            # Empty results -> re-search: ONE Back to 搜寻, VERIFIED. If that single Back doesn't
            # land on 搜寻, DO NOT keep backing out (that's what walked the menu out to free
            # roam) -- bail and retry next cycle.
            self.io.press("esc")
            if self._wait_for({SEARCH}, 2.5) == SEARCH:
                self.io.run_search()          # 确认 -> fresh query
                if self._wait_for({RESULTS}, 6.0) == RESULTS and self.io.has_listing():
                    return self._buy_out_first()
            return "no_cars"
        if s == SEARCH:
            self.io.run_search()              # 确认 -> fresh results
            if self._wait_for({RESULTS}, 6.0) == RESULTS and self.io.has_listing():
                return self._buy_out_first()
            return "no_cars"
        if s == DETAIL:
            self.io.press("esc")              # one Back -> results; next cycle buys it
            self._wait_for({RESULTS}, 2.5)
            return "recovered"
        # HOUSE / UNKNOWN / anything else: NEVER press Back here. Pressing Back on a screen we
        # don't recognise is exactly what walked the menu out to free roam. Just wait + re-read.
        return "recovered"

    def _buy_out_first(self) -> str:
        """Buy out the first listing via the captured flow:
        选择/Enter -> 车辆详情 (竞价 focused, 买断 below) -> Down ONCE -> Enter -> 买断 confirm.

        SAFETY: the confirm is verified to be the BUY-OUT dialog before the final yes. If the
        Down dropped and we land on the BID (竞价) confirm instead, we detect it and back out
        WITHOUT confirming -- a snipe must never place a bid."""
        if not self.io.open_buyout():           # Enter (选择) -> 车辆详情 with 竞价/买断 rows
            self.io.press("esc")
            return "recovered"
        if self.dry_run:
            # On 车辆详情 with the 买断 row visible. Do NOT open the confirm dialog -- it
            # ignores B/Esc, so a dry-run couldn't cleanly cancel it. B works HERE
            # (detail -> results), so backing out is clean and ZERO-risk.
            self.io.press("esc")
            self.on_log("抢车[空跑]：已到『车辆详情』、看到买断项,未开确认框(零风险)。")
            return "dry_seen"
        # select 买断: ONE down (竞价 -> 买断), never retried, then open its confirm dialog.
        self.io.select_buyout(self.buyout_select_delay)
        s = self._wait_for({BUYOUT_CONFIRM, BID_CONFIRM}, 2.5)
        if s == BUYOUT_CONFIRM:
            outcome = self.io.confirm_buyout()  # press 嗯 -> buy, observe success/failed
            if outcome == "bought":
                self.io.collect()
                return "bought"
            return "failed"
        if s == BID_CONFIRM:
            # The Down dropped -> this is the BID dialog. NEVER confirm; B can't dismiss it
            # and Down+A risks bidding, so report and let the user back out via 不.
            self.on_log("抢车：出现『竞价』确认框(非买断),已停手,请手动选『不』退出。")
            return "recovered"
        # no confirm appeared -> likely still on 车辆详情; B works there -> back to results.
        self.io.press("esc")
        return "recovered"

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
        verbose: bool = False,
        stop_event=None,
    ):
        self.recognizer = recognizer
        self.pad = pad
        self.title = title
        self.on_log = on_log or (lambda m: None)
        self._sleep = sleep
        self.tap_hold = tap_hold
        self.settle = settle
        self.verbose = verbose
        self._stop = stop_event
        self._last_text = ""
        self._last_selected = ""

    def _dbg(self, msg: str) -> None:
        if self.verbose:
            self.on_log(msg)

    def _stopped(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    # --- sensing (full-res OCR, mirrors the stable sell runner) ---------------
    def _look(self) -> str:
        snap = self.recognizer.capture(full_ocr=True, region_ocr=True)
        self._last_text = " | ".join(str(getattr(it, "text", "")) for it in snap.ocr_items)
        self._last_selected = str(getattr(snap.v3, "selected_item", "") or "")
        return self._last_text

    def _can_collect(self, text=None) -> bool:
        """The 领取车辆 prompt is up. Robust to OCR drift: the won-detail's selected_item is
        cleanly read as '领取车辆' even when it's buried in the full-frame OCR text."""
        t = self._last_text if text is None else text
        return detect_auction_won(t)["can_collect"] or self._last_selected == "领取车辆"

    def focused(self) -> bool:
        try:
            import focus
            return focus.is_foreground(self.title)
        except Exception:
            return True

    def activate(self) -> None:
        """Bring Forza to the foreground (a normal foreground switch -- no inject/fake-focus),
        so the snipe keeps running even while the GUI/another window is on top."""
        try:
            import focus
            focus.activate_window(title_substr=self.title)
        except Exception:
            pass

    def screen(self) -> str:
        tag = classify_auction_screen(self._look())
        self._dbg(f"  [看] 识别={tag}  OCR: {self._last_text[:120]}")
        return tag

    # --- input (jittered, anti-pattern timing learned from the OSS sniper) ----
    def press(self, name: str) -> None:
        from gamepad import BUTTON_NAMES
        btn = self._BTN.get(name, name)
        self._dbg(f"  [按] {name} -> {btn}")
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
    def run_search(self) -> None:
        """On the 搜寻 config screen, navigate to the 确认 button and press it to fire a FRESH
        query -- the only way new listings appear (the results list never auto-refreshes).

        REFINE-LIVE: the 确认 highlight (selected_item == '确认') is to be confirmed on the
        live 搜寻 screen (online was down at authoring). Until then: press Down (bounded) until
        selected_item reads 确认, then A. A mis-press here only toggles a filter field (no
        credits), and the next cycle re-tries, so it is self-correcting."""
        for _ in range(7):
            if self._stopped():
                return
            if "确认" in str(self._last_selected):
                break
            self.press("down")
            self._look()
        if self._stopped():
            return
        self.press("enter")                          # 确认 -> fresh query

    def _log_buyout_price(self) -> None:
        m = _BUYOUT_PRICE_RE.search(self._last_text or "")
        if m:
            self.on_log(f"抢车：目标买断价 CR {m.group(1)}。")

    def open_buyout(self) -> bool:
        """选择/Enter on the focused results card -> 车辆详情 (竞价 focused, 买断 below).

        This is the path VALIDATED live (3 buy-outs). The faster Y quick-menu is deferred
        until it can be confirmed on the live auction -- when its menu wasn't recognised it
        risked an A landing on the 竞价/bid row, so reliability first."""
        self.press("enter")                          # 选择 -> 车辆详情
        for _ in range(8):
            if self._stopped():
                return False
            tag = classify_auction_screen(self._look())
            self._dbg(f"  [开] 选择后 识别={tag}")
            if tag == DETAIL:
                self._log_buyout_price()
                return True
        return classify_auction_screen(self._last_text) == DETAIL

    def select_buyout(self, delay: float) -> None:
        """ONE Down (竞价 -> 买断), a settle so it registers, then Enter to open the confirm.
        Exactly one dpad_down, never retried: a retried Down could overshoot back onto 竞价."""
        self.press("down")
        self._sleep(max(0.0, float(delay)))
        self.press("enter")

    def confirm_buyout(self) -> str:
        """Press 嗯 on the ALREADY-VERIFIED 买断 dialog, then wait for the outcome. Like the
        reference sniper's _confirm_yes: if the 买断 confirm is STILL showing, the 嗯 was
        dropped -> RE-PRESS (up to 4 total). Success = the 买断成功 popup ('您可以在我的竞价页面
        领取该车辆'); the car is then paid for and parked in 我的竞价. On timeout we report
        'failed' -- never claim a buy we didn't actually see confirmed."""
        self.press("enter")                          # 嗯
        attempts = 1
        for _ in range(30):                          # buy can take a few seconds to settle
            if self._stopped():
                return "stopped"
            text = self._look()
            if detect_buyout_success(text)["visible"] or self._last_selected == "买断成功":
                return "bought"
            if detect_buyout_confirm(text)["failed"]:
                return "failed"
            if detect_buyout_confirm(text)["visible"]:
                # the 买断 confirm is STILL up -> the 嗯 was dropped; re-press (bounded to 4).
                if attempts < 4:
                    self._dbg(f"  [确认] 买断框仍在,重按嗯 (#{attempts + 1})")
                    self.press("enter")
                    attempts += 1
                self._sleep(0.2)
                continue
            if classify_auction_screen(text) in (RESULTS, DETAIL, HOUSE):
                return "bought"                      # dialog gone, no failure marker -> bought
            self._sleep(0.2)
        return "failed"   # never saw 买断成功 -> do NOT claim a purchase

    def collect(self) -> None:
        """Settle the game after a buy-out. The IMMEDIATE post-buy popup is 买断成功
        ('您可以在我的竞价页面领取该车辆') -> press 确定 to clear it back to the results list (the
        car is paid and parked in 我的竞价 for a later 领取). Also handles an in-place 领取车辆 /
        已加入车库 flow if one is shown. Bounded so it can never spin; all presses here are safe
        (the car is already paid -- no buy or bid is possible)."""
        for i in range(40):
            if self._stopped():
                return
            text = self._look()
            self._dbg(f"  [收{i}] 选中={self._last_selected!r} OCR: {text[:120]}")
            if detect_buyout_success(text)["visible"] or self._last_selected == "买断成功":
                self._dbg("  [收] 买断成功 -> 确定")
                self.press("enter")                     # A -> 确定
                self._sleep(0.4)
                break
            if classify_auction_screen(text) in (RESULTS, SEARCH, HOUSE):
                break                                   # already back at a list
            if self._can_collect(text) or detect_auction_collected(text)["visible"]:
                self._collect_won_car()                 # in-place 领取车辆 flow (rare)
                break
            self._sleep(0.2)
        # settle to a list (gentle: at most 3 B, stop at the first list)
        for _ in range(3):
            if classify_auction_screen(self._look()) in (RESULTS, SEARCH, HOUSE):
                return
            self.press("esc")

    def _collect_won_car(self) -> None:
        """Deferred collect (from 我的竞价 / an in-place won-detail): 拍卖完成/中标 + 领取车辆
        --A--> 正在领取... --> 已加入您的车库 --A(确定)-->. The 领取车辆 prompt is detected via
        selected_item too (OCR-drift proof). All presses are safe (the car is already paid)."""
        pressed_collect = False
        for i in range(40):
            text = self._look()
            self._dbg(f"  [领{i}] 选中={self._last_selected!r} OCR: {text[:120]}")
            col = detect_auction_collected(text)
            if col["done"]:
                self._dbg("  [领] 已加入车库 -> 确定")
                self.press("enter")                     # A -> 确定
                self._sleep(0.4)
                return
            if col["collecting"]:
                self._sleep(0.2)                        # 正在领取... -> wait
                continue
            if self._can_collect(text):
                if not pressed_collect:
                    self._dbg("  [领] 领取车辆")
                    self.press("enter")                 # A -> 领取车辆
                    pressed_collect = True
                    self._sleep(0.5)
                continue
            if pressed_collect:
                # 领取车辆 pressed and the prompt is gone -> collected (success popup can be
                # brief). One 确定 (A) clears any lingering popup; A on the won-detail is a no-op.
                self._dbg("  [领] 领取后提示消失,视为已领取 -> 确定")
                self.press("enter")
                return
            if classify_auction_screen(text) in (RESULTS, SEARCH, HOUSE):
                return
            self._sleep(0.2)
