"""Buy-all-unowned-cars loop (autoshow 车展). DRY-RUN supported.

Flow mapped LIVE by driving the game (validated end-to-end):

  车展 grid (vehicle_buy_grid)
    -- Y --> 筛选 (eventlab_filter): 价格适中 / 已拥有 / 未拥有 / ...
       -- Down,Down --> 未拥有  -- A (勾选) --  -- B (关闭) -->  filtered grid (un-owned only)
    -- A (选择 the focused un-owned car) -->  [idle_showcase ~5s while 推荐设计 LOADS]  -->
       推荐设计 (design_grid) -- Y --> 出厂颜色 (color_select) -- A --> 车辆预览 (car_preview) -- A -->
       购买确认 (purchase_confirm: "是否要花费 N 购买此车辆?") -- A (购买) -->
       新车展示 (idle_showcase) -- B --> 车辆展示 (photo_mode) -- B --> 购买与出售 (autoshow_buy_sell)
       -- A (车展, slow load) --> grid again.

KEY facts (validated live):
- After selecting a car, the design page loads SLOWLY and shows the idle car showcase
  (idle_showcase) for several seconds first, THEN becomes design_grid. So the buy must wait for
  design_grid (tolerating idle_showcase), not give up after a couple seconds.
- idle_showcase is ambiguous (it's BOTH the design-loading screen AND the post-purchase
  cinematic AND the menu screensaver), so the buy is driven by a PHASE-AWARE sequential method
  (buy_focused_car), not a stateless screen dispatch.
- The 未拥有 filter RESETS when you leave + re-enter the showroom, so the loop RE-APPLIES it each
  time it lands on a fresh grid. A bought car drops out of the filtered grid, so the next
  un-owned car is focused and the loop converges.

SAFETY: only ever buys from the FILTERED (未拥有) grid; dry_run walks the whole path but CANCELS
at the 购买确认 dialog (B) instead of buying; stops at max_cars (None=unlimited) / stop / when the
grid yields no more buyable car. The buy sub-flow mirrors the validated 22B buy.

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
SHOWCASE = "idle_showcase"      # design-loading / post-purchase cinematic / menu screensaver
CARVIEW = "photo_mode"          # post-purchase static car view
TRAVEL_MODAL = "modal_warning"  # 移动至嘉年华 (only if started off-site)
DISCONNECT = "controller_disconnected"

_PRICE_RE = re.compile(r"花费[^\d]{0,4}(\d{1,3}(?:,\d{3})+)")


class UnownedBuyer:
    """Drives the buy-all-unowned loop through an injectable IO."""

    def __init__(
        self,
        io,
        *,
        dry_run: bool = True,
        max_cars: int | None = None,
        max_minutes: float = 120.0,
        on_log=None,
        clock=time.monotonic,
        sleeper=time.sleep,
        stop_event=None,
        auto_focus: bool = True,
    ):
        self.io = io
        self.dry_run = dry_run
        self.max_cars = None if max_cars is None else max(1, int(max_cars))
        self.max_minutes = float(max_minutes)
        self.on_log = on_log or (lambda m: None)
        self.clock = clock
        self.sleeper = sleeper
        self._stop = stop_event
        self.auto_focus = auto_focus
        self.bought = 0
        self.started_at = None
        self._filter_applied = False    # re-applied on every fresh grid (it resets on re-entry)
        self._filter_fail = 0
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
            self.io.press("a")
            return "recovered"

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
            # freshly FILTERED grid -> buy the focused (first un-owned) car via the phase-aware
            # sequential flow. Pressing buy leaves the grid, so the filter must be re-applied on
            # the next fresh grid.
            self._filter_applied = False
            result = self.io.buy_focused_car(self.dry_run)
            if result == "bought":
                self.bought += 1
                self.on_log(f"买未拥有：已买下第 {self.bought} 辆。")
                return "step"
            if result == "dry_seen":
                self.on_log("买未拥有[空跑]：已走到购买确认并取消(零风险)。")
                return "dry_seen"
            if result == "no_car":
                return "empty"
            return "recovered"   # failed -> re-orient on the next loop

        if s == MENU:
            self._filter_applied = False
            self.io.enter_showroom()   # A on 车展 -> grid (slow load); robust inside the IO
            return "step"

        if s == TRAVEL_MODAL:
            self.io.press("a")         # 移动至嘉年华 嗯
            return "step"

        # FILTER mid-op / SHOWCASE / CARVIEW / unknown -> wait + re-read (never a blind press here;
        # the IO methods own those transitional screens).
        return "recovered"

    def run(self) -> str:
        """Loop until max_cars / max_minutes / empty grid / stop. Returns the stop reason."""
        self.started_at = self.clock()
        limit = "不限" if self.max_cars is None else f"最多 {self.max_cars} 辆"
        self.on_log(
            f"买未拥有{'[空跑]' if self.dry_run else ''}启动：{limit} / "
            f"{self.max_minutes:.0f} 分钟。请先停在『车展』车辆网格页。"
        )
        while not self._stopped():
            if self.max_cars is not None and self.bought >= self.max_cars:
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

    Buttons captured live: Enter=A, Esc=B, Y=Y, Down=dpad_down. The buy sub-flow + its slow loads
    are driven by phase-aware sequential methods (buy_focused_car / enter_showroom) so the
    ambiguous idle_showcase screen is handled correctly in each phase."""

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

    def _wait_screen(self, tags, timeout: float) -> str | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._stopped():
                return None
            s = self._look()
            if s in tags:
                return s
            self._sleep(0.2)
        return None

    def _log_buy_price(self) -> None:
        m = _PRICE_RE.search(self._last_text or "")
        if m:
            self.on_log(f"买未拥有：本辆买价 CR {m.group(1)}。")

    # -- the captured filter + buy flow ---------------------------------------
    def apply_unowned_filter(self) -> bool:
        """Y -> 筛选 -> Down,Down (-> 未拥有) -> A (勾选) -> B (关闭) -> filtered grid. The grid can
        briefly show its idle car (idle_showcase) before/after, so accept either GRID or
        idle_showcase as 'back on the grid'. REFINE-LIVE: 未拥有 is the 3rd row from the top."""
        self.press("y")
        if self._wait_screen({FILTER}, 4.0) != FILTER:
            self.on_log("买未拥有：按 Y 没打开筛选弹窗,跳过本次筛选。")
            return False
        self.press("down")
        self.press("down")           # 价格适中 -> 已拥有 -> 未拥有
        self.press("a")              # 勾选 未拥有
        self.press("b")              # 关闭筛选
        if self._wait_screen({GRID}, 4.0) == GRID:
            self.on_log("买未拥有：已勾选『未拥有』筛选,只买没有的车。")
            return True
        return False

    def buy_focused_car(self, dry_run: bool) -> str:
        """Select the focused (un-owned) car and complete the purchase, then return to the
        showroom menu. PHASE-AWARE: after 选择, the design page loads slowly (idle_showcase shown
        for several seconds first), so wait for design_grid; if it never appears, A opened no buy
        (no buyable car) -> no_car. Returns: bought | dry_seen | no_car | failed."""
        self.press("a")                                   # 选择 the focused car
        # The 推荐设计 page loads slowly (idle car showcase shown meanwhile). Wait for it; if it
        # never appears, there was no buyable car under the cursor.
        if not self._wait_screen({DESIGN}, 18.0):
            self._dbg("  [买] 选车后 18s 内未出现推荐设计页")
            return "no_car"
        self._log_buy_price()
        deadline = time.monotonic() + 50.0
        while time.monotonic() < deadline:
            if self._stopped():
                return "failed"
            s = self._look()
            self._dbg(f"  [买] {s}")
            if s == DESIGN:
                self.press("y")                           # 推荐设计 -> 出厂颜色
                self._wait_screen({COLOR, PREVIEW, CONFIRM}, 8.0)
            elif s == COLOR:
                self.press("a")                           # 确认默认颜色 -> 预览
                self._wait_screen({PREVIEW, CONFIRM}, 8.0)
            elif s == PREVIEW:
                self.press("a")                           # 预览 -> 购买确认
                self._wait_screen({CONFIRM}, 8.0)
            elif s == CONFIRM:
                if dry_run:
                    self.press("b")                       # cancel -- zero spend
                    return "dry_seen"
                self.press("a")                           # 购买
                return "bought" if self._finish_purchase(28.0) else "failed"
            elif s in (GRID, MENU):
                return "no_car"                           # fell back without buying
            else:
                self._sleep(0.6)                          # idle_showcase / loading -> wait
        return "failed"

    def _finish_purchase(self, timeout: float) -> bool:
        """After 购买, the new car plays a showcase. Confirm the buy by reaching the post-buy
        showcase, then back out (B,B) toward the 购买与出售 menu so the loop can re-enter + re-filter."""
        if not self._wait_screen({SHOWCASE, CARVIEW, MENU}, timeout):
            return False
        deadline = time.monotonic() + 16.0
        while time.monotonic() < deadline:
            if self._stopped():
                return True
            s = self._look()
            if s == MENU:
                return True
            if s in (SHOWCASE, CARVIEW):
                self.press("b")                           # showcase -> car view -> menu
            else:
                self._sleep(0.5)
        return True                                       # bought; loop handles wherever we landed

    def enter_showroom(self) -> bool:
        """A on 车展 in the 购买与出售 menu -> the vehicle grid (slow first load; the menu may show
        its idle car screensaver). Retries A on 车展 a few times until the grid appears."""
        for _ in range(3):
            if self._stopped():
                return False
            self.press("a")                               # A on 车展 (focused after a buy)
            if self._wait_screen({GRID}, 12.0) == GRID:
                return True
            s = self._look()
            if s == SHOWCASE:
                self.press("up")                          # wake the menu, re-focus 车展
            # else (still MENU) -> loop retries A
        return self._look() == GRID
