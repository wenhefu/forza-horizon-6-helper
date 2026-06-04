"""Buy-all-unowned-cars loop (autoshow 车展). DRY-RUN by default.

Flow mapped LIVE by driving the game (one real purchase validated end-to-end):

  车展 grid (vehicle_buy_grid)
    -- Y --> 筛选 (eventlab_filter): 价格适中 / 已拥有 / 未拥有 / ...
       -- Down,Down --> 未拥有  -- A (勾选) --  -- B (关闭) -->  filtered grid (un-owned only)
    -- A (选择 the focused un-owned car) --> 推荐设计 (design_grid)
       -- Y --> 出厂颜色 (color_select) -- A --> 车辆预览 (car_preview) -- A -->
       购买确认 (purchase_confirm: "是否要花费 N 购买此车辆?") -- A (购买) -->
       新车展示 (idle_showcase) -- B --> 车辆展示 (photo_mode) -- B --> 购买与出售 (autoshow_buy_sell)
       -- A (车展, slow load) --> grid again.

KEY fact (validated): the 未拥有 filter RESETS when you leave + re-enter the showroom, so the
loop RE-APPLIES it each time it lands on a fresh grid. A bought car then drops out of the
filtered grid, so the cursor lands on the next un-owned car -> the loop converges.

SAFETY: only ever buys from the FILTERED (未拥有) grid, never an unfiltered one; dry_run does the
whole path but CANCELS at the 购买确认 dialog (B) instead of buying; stops at max_cars / stop /
when the grid yields no more buyable car. The reused buy sub-flow (design->color->preview->
confirm) is the SAME one validated for the 22B buy.

The IO is injectable so the loop logic is unit-tested without a game (see tests/test_unowned.py).
"""
from __future__ import annotations

import random
import re
import time

# v3 screen tags (exactly what the recognizer reported while driving the game live).
GRID = "vehicle_buy_grid"
FILTER = "eventlab_filter"
DESIGN = "design_grid"
COLOR = "color_select"
PREVIEW = "car_preview"
CONFIRM = "purchase_confirm"
MENU = "autoshow_buy_sell"
SHOWCASE = "idle_showcase"      # post-purchase cinematic
CARVIEW = "photo_mode"          # post-purchase static car view
TRAVEL_MODAL = "modal_warning"  # 移动至嘉年华 (only if started off-site)
DISCONNECT = "controller_disconnected"

_PRICE_RE = re.compile(r"花费[^\d]{0,4}(\d{1,3}(?:,\d{3})+)")
_BUY_SUBFLOW = {DESIGN, COLOR, PREVIEW, CONFIRM}


class UnownedBuyer:
    """Drives the buy-all-unowned loop through an injectable IO."""

    def __init__(
        self,
        io,
        *,
        dry_run: bool = True,
        max_cars: int = 5,
        max_minutes: float = 120.0,
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
        self.on_log = on_log or (lambda m: None)
        self.clock = clock
        self.sleeper = sleeper
        self._stop = stop_event
        self.auto_focus = auto_focus
        self.bought = 0
        self.started_at = None
        self._filter_applied = False     # re-applied on every fresh grid (it resets on re-entry)
        self._pending_purchase = False   # a 购买确认 was just confirmed; count it at the showcase
        self._filter_fail = 0            # consecutive failures to open/apply the filter
        self._refocus_logged = False

    def _stopped(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    def _ensure_focus(self) -> bool:
        if self.io.focused():
            return True
        if self.auto_focus and hasattr(self.io, "activate"):
            if not self._refocus_logged:
                self.on_log("买未拥有：Forza 不在前台,正自动切回(按停止可中止)。")
                self._refocus_logged = True
            self.io.activate()
            self.sleeper(0.4)
        return self.io.focused()

    def run_once(self) -> str:
        """Handle ONE screen. Returns: bought | dry_seen | step | empty | recovered."""
        if not self._ensure_focus():
            return "recovered"
        s = self.io.screen()

        if s == DISCONNECT:
            self.io.press("a")                       # reconnect/confirm
            return "recovered"

        if s == CONFIRM:
            price = self.io.read_price()
            if self.dry_run:
                self.io.press("b")                   # cancel -- dry-run never spends
                self.on_log(f"买未拥有[空跑]：已走到购买确认{('，价格 CR ' + price) if price else ''}，按 B 取消(零风险)。")
                return "dry_seen"
            self._pending_purchase = True
            self.io.confirm_buy()                    # A -> 购买
            self.on_log(f"买未拥有：确认购买{('，价格 CR ' + price) if price else ''}。")
            return "step"

        if s == DESIGN:
            self.io.press("y")                       # 推荐设计 -> 出厂颜色
            return "step"
        if s == COLOR:
            self.io.press("a")                       # 确认默认颜色 -> 预览
            return "step"
        if s == PREVIEW:
            self.io.press("a")                       # 预览 -> 购买确认
            return "step"

        if s in (SHOWCASE, CARVIEW):
            if self._pending_purchase:
                self.bought += 1
                self._pending_purchase = False
                self.on_log(f"买未拥有：已买下第 {self.bought} 辆。")
            self._filter_applied = False             # we're leaving the grid -> re-filter on return
            self.io.press("b")                       # back toward the showroom menu
            return "step"

        if s == MENU:
            self._filter_applied = False
            self.io.enter_showroom()                 # A on 车展 (slow load) -> grid
            return "step"

        if s == TRAVEL_MODAL:
            self.io.press("a")                       # 移动至嘉年华 嗯
            return "step"

        if s == GRID:
            if not self._filter_applied:
                if self.io.apply_unowned_filter():
                    self._filter_applied = True
                    self._filter_fail = 0
                else:
                    self._filter_fail += 1
                    if self._filter_fail >= 3:
                        self.on_log("买未拥有：多次无法打开/应用『未拥有』筛选,停止避免乱买。")
                        return "empty"
                return "step"
            # freshly FILTERED grid: buy the focused (first un-owned) car.
            self._filter_applied = False             # pressing buy leaves the grid (re-filter on return)
            if self.io.open_buy():
                return "step"
            # The filter is applied but A opened no buy sub-flow -> no un-owned car left -> done.
            return "empty"

        return "recovered"                           # FILTER mid-op / unknown -> wait + re-read

    def run(self) -> str:
        """Loop until max_cars / max_minutes / empty grid / stop. Returns the stop reason."""
        self.started_at = self.clock()
        self.on_log(
            f"买未拥有{'[空跑]' if self.dry_run else ''}启动：最多 {self.max_cars} 辆 / "
            f"{self.max_minutes:.0f} 分钟。请先停在『车展』车辆网格页。"
        )
        while not self._stopped():
            if self.bought >= self.max_cars:
                return "max_cars"
            if (self.clock() - self.started_at) / 60.0 >= self.max_minutes:
                return "max_minutes"
            outcome = self.run_once()
            if outcome == "empty":
                self.on_log("买未拥有：筛选后已无可买的未拥有车辆,结束。")
                return "no_more_cars"
            if outcome == "dry_seen" and self.dry_run:
                return "dry_done"
            self.sleeper(0.12 + random.uniform(0.0, 0.08))
        return "stopped"


class UnownedBuyIO:
    """Real game-facing IO: OUR recognizer (v3.screen) for sensing + the virtual gamepad for
    input -- foreground-only, read-only capture, no injection. Mirrors AuctionIO.

    Buttons captured live: Enter=A, Esc=B, Y=Y, Down=dpad_down. The filter is opened with Y and
    the 未拥有 row is Down,Down from the top (价格适中). REFINE-LIVE markers note the few spots
    whose exact tokens/positions were validated by driving but may want a live re-check."""

    _BTN = {
        "enter": "a", "a": "a", "esc": "b", "b": "b", "y": "y",
        "down": "dpad_down", "up": "dpad_up", "left": "dpad_left", "right": "dpad_right",
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

    def _dbg(self, msg: str) -> None:
        if self.verbose:
            self.on_log(msg)

    def _stopped(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    def _look(self) -> str:
        snap = self.recognizer.capture(full_ocr=True, region_ocr=True)
        self._last_text = " | ".join(str(getattr(it, "text", "")) for it in snap.ocr_items)
        return str(getattr(snap.v3, "screen", "") or "")

    def focused(self) -> bool:
        try:
            import focus
            return focus.is_foreground(self.title)
        except Exception:
            return True

    def activate(self) -> None:
        try:
            import focus
            focus.activate_window(title_substr=self.title)
        except Exception:
            pass

    def screen(self) -> str:
        tag = self._look()
        self._dbg(f"  [看] screen={tag}  OCR: {self._last_text[:120]}")
        return tag

    def press(self, name: str) -> None:
        from gamepad import BUTTON_NAMES
        btn = self._BTN.get(name, name)
        if btn in BUTTON_NAMES:
            self.pad.tap(btn, hold=self.tap_hold)
        self._sleep(self.settle + random.uniform(0.0, 0.12))

    def read_price(self) -> str:
        m = _PRICE_RE.search(self._last_text or "")
        return m.group(1) if m else ""

    def _wait_screen(self, tags, timeout: float) -> str | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._stopped():
                return None
            s = self._look()
            if s in tags:
                return s
            self._sleep(0.15)
        return None

    def apply_unowned_filter(self) -> bool:
        """Y -> 筛选 -> Down,Down (-> 未拥有) -> A (勾选) -> B (关闭) -> filtered grid.
        REFINE-LIVE: 未拥有 is the 3rd row (Down,Down from 价格适中) on a freshly-opened filter."""
        self.press("y")
        if self._wait_screen({FILTER}, 3.0) != FILTER:
            self.on_log("买未拥有：按 Y 没打开筛选弹窗,跳过本次筛选。")
            return False
        self.press("down")
        self.press("down")                           # 价格适中 -> 已拥有 -> 未拥有
        self.press("a")                              # 勾选 未拥有
        self.press("b")                              # 关闭筛选
        if self._wait_screen({GRID}, 3.0) == GRID:
            self.on_log("买未拥有：已勾选『未拥有』筛选,只买没有的车。")
            return True
        return False

    def open_buy(self) -> bool:
        """A (选择) on the focused un-owned car -> the buy sub-flow (推荐设计). Returns True when a
        buy sub-flow screen appears; False if A did not open one (no buyable car -> grid empty)."""
        self.press("a")
        return self._wait_screen(_BUY_SUBFLOW, 6.0) in _BUY_SUBFLOW

    def confirm_buy(self) -> None:
        self.press("a")                              # 购买

    def enter_showroom(self) -> None:
        """A on 车展 in the 购买与出售 menu -> the grid (slow first load)."""
        self.press("a")
        self._wait_screen({GRID, SHOWCASE}, 12.0)    # tolerate the slow showroom load
