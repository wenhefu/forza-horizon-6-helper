"""Survey the 车辆收藏 (Vehicle Collection) grid: catalog every UN-OWNED car and how each
one is obtained. READ-ONLY -- it never buys anything.

Flow mapped LIVE by driving the game (收集簿 -> 旅行家 -> 车辆收藏):

  车辆收藏 grid: a 5-column card grid. A card showing the gray "DISCOVER JAPAN" placeholder
  (instead of a car render) = the car is NOT yet owned (the user's rule: "每个没显示车的方格
  都表明还没拥有"). A full-color car render = owned/discovered.

  For each card, the bottom prompt offers 购买 on the **Menu/≡ button (start)** (keyboard = Space).
  Pressing it opens a "车辆收藏" popup that states how the car is obtained:
    * buyable:   "此车可通过以下途径获得：抽奖,车展。是否要从车展购买这辆车?"  [取消(focused) / 确认]
    * reward:    "此车辆可能在季节性赛事或嘉年华游戏列表中作为奖励出现。"          [确定]
  Pressing **A** safely dismisses BOTH (取消 is default-focused on the buy popup -> A cancels;
  the reward popup's only button is 确定 -> A dismisses). So the survey reads the obtain method
  WITHOUT ever buying.

The recognizer does not have a tag for this grid (it mislabels it unknown / vehicle_buy_grid /
modal_warning), so this module senses the grid itself from the frame + OCR:
  - un-owned = the card image-area edge strips are a flat neutral gray (the placeholder), vs a
    car render's white studio background (slight tint, higher variance).  [validated 15/15 cells]
  - the focused card is found by the bright lime focus-ring's centroid (grid-band lime pixels).
  - car names are read from the OCR items at each cell's name band.

All geometry is normalized for the 16:9 client area the helper enforces. The IO is injectable so
the traversal logic is unit-tested without a game (see tests/test_unowned_survey.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import time

# --- grid geometry (normalized, 16:9) -- measured live from the 车辆收藏 grid ----------------
COL_CENTERS = (0.152, 0.324, 0.496, 0.667, 0.839)   # 5 columns
ROW_CENTERS = (0.316, 0.548, 0.779)                 # 3 visible card rows (centers)
HALF_W = 0.0838
HALF_H = 0.1128
NAME_DY = 0.074          # name text sits this far below a card's center
NAME_TOL_Y = 0.018
NAME_TOL_X = 0.070

OBTAIN_BUY = "buy"
OBTAIN_REWARD = "reward"
OBTAIN_UNKNOWN = "unknown"

# Canonical obtain-method labels (zh) the report groups by.
METHOD_AUTOSHOW = "车展"
METHOD_WHEELSPIN = "抽奖"
METHOD_REWARD = "季节赛事/嘉年华奖励"

_OBTAIN_RE = re.compile(r"可通过以下途径获得[:：]?\s*([^。\n]+?)(?:。|是否|$)")


def cell_image_box(row: int, col: int):
    """Normalized (x0, y0, x1, y1) of a cell's IMAGE area (skips the rarity tag + the name)."""
    cx = COL_CENTERS[col]
    cy = ROW_CENTERS[row]
    top = cy - HALF_H
    height = 2 * HALF_H
    return (cx - HALF_W, top + 0.10 * height, cx + HALF_W, top + 0.62 * height)


def is_placeholder_cell(arr, row: int, col: int) -> bool:
    """True if the cell is the gray 'DISCOVER JAPAN' placeholder (UN-OWNED).

    A placeholder's image-area side strips are a flat, perfectly neutral gray (~225,225,225); a
    car render has a near-white studio background with a slight green/blue tint and higher
    variance. arr is an HxWx3 uint8 RGB array.
    """
    import numpy as np

    h, w = arr.shape[:2]
    x0, y0, x1, y1 = cell_image_box(row, col)
    ix0, ix1 = int(x0 * w), int(x1 * w)
    iy0, iy1 = int(y0 * h), int(y1 * h)
    if ix1 - ix0 < 12 or iy1 - iy0 < 6:
        return False
    img = arr[iy0:iy1, ix0:ix1].astype(int)
    strip = max(8, (ix1 - ix0) // 9)
    edge = np.concatenate(
        [img[:, :strip].reshape(-1, 3), img[:, -strip:].reshape(-1, 3)]
    )
    em = edge.mean(0)
    std = float(edge.std())
    neutral = abs(em[0] - em[1]) + abs(em[1] - em[2]) + abs(em[0] - em[2])
    # Placeholder edges are a flat, perfectly NEUTRAL gray (neutral~=0, low variance); a car
    # render has a tinted near-white studio bg + the car -> non-neutral AND high variance. Both
    # signals must agree (validated 30/30 cells across two live frames).
    return bool(em.mean() < 240.0 and std < 22.0 and neutral < 9.0)


def focused_cell(arr, *, min_lime: int = 700):
    """Locate the cursor (the bright lime focus-ring) -> (row, col), or None if no clear ring.

    The ring sits in the gutter around the focused card; its grid-band centroid maps cleanly to
    the focused cell. arr is HxWx3 uint8 RGB.
    """
    import numpy as np

    h, w = arr.shape[:2]
    R, G, B = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    lime = (R > 150) & (R < 240) & (G > 225) & (B < 95)
    ys, xs = np.where(lime)
    if len(xs) == 0:
        return None
    band = (ys > 0.14 * h) & (ys < 0.95 * h)
    xs, ys = xs[band], ys[band]
    if len(xs) < min_lime:
        return None
    cx, cy = xs.mean() / w, ys.mean() / h
    col = min(range(5), key=lambda c: abs(COL_CENTERS[c] - cx))
    row = min(range(3), key=lambda r: abs(ROW_CENTERS[r] - cy))
    return (row, col)


_NAME_BAD = ("DISCOVER", "JAPAN", "普通", "稀有", "史诗", "传奇")


def read_cell_name(ocr_items, row: int, col: int) -> str:
    """The car name shown under a cell -- the OCR item nearest the cell's name band. Returns ''
    when nothing matches (e.g. an empty trailing cell)."""
    band_y = ROW_CENTERS[row] + NAME_DY
    band_x = COL_CENTERS[col]
    best = ""
    best_dy = NAME_TOL_Y + 1.0
    for it in ocr_items:
        ncx = getattr(it, "ncx", None)
        ncy = getattr(it, "ncy", None)
        if ncx is None or ncy is None:
            continue
        if abs(ncx - band_x) > NAME_TOL_X:
            continue
        dy = abs(ncy - band_y)
        if dy > NAME_TOL_Y:
            continue
        text = (getattr(it, "text", "") or "").strip()
        if not text or len(text) < 2:
            continue
        # skip year/rarity-only fragments
        if any(bad in text for bad in _NAME_BAD):
            continue
        if re.fullmatch(r"\d{4}.*", text) and dy > 0.012:
            continue
        if dy < best_dy:
            best_dy = dy
            best = text
    return best


def classify_obtain(text: str):
    """Classify a 购买 popup's text -> (kind, [method labels]).

    kind in buy|reward|unknown. methods is the list of canonical zh labels the report groups by.
    """
    t = text or ""
    if ("作为奖励出现" in t) or ("季节" in t and "奖励" in t) or ("嘉年华游戏列表" in t):
        return OBTAIN_REWARD, [METHOD_REWARD]
    m = _OBTAIN_RE.search(t)
    if m:
        raw = m.group(1)
        methods = []
        for tok in re.split(r"[,，、/]+", raw):
            tok = tok.strip()
            if not tok:
                continue
            if "车展" in tok:
                methods.append(METHOD_AUTOSHOW)
            elif "抽奖" in tok or "转盘" in tok:
                methods.append(METHOD_WHEELSPIN)
            else:
                methods.append(tok)
        # de-dup preserving order
        seen = set()
        methods = [x for x in methods if not (x in seen or seen.add(x))]
        return OBTAIN_BUY, methods or [METHOD_AUTOSHOW]
    return OBTAIN_UNKNOWN, []


@dataclass
class Cell:
    name: str
    placeholder: bool


@dataclass
class GridView:
    on_grid: bool
    focused: tuple | None                  # (row, col) of the cursor, or None
    cells: dict = field(default_factory=dict)   # (row, col) -> Cell  (visible rows only)
    text: str = ""


@dataclass
class SurveyResult:
    name: str
    kind: str            # buy | reward | unknown
    methods: list


class UnownedSurveyor:
    """Walks the collection grid (snake order, self-locating via the focus ring), pressing 购买
    on every UN-OWNED card to read its obtain method. Never buys. Returns a SurveyResult list."""

    MAX_STEPS = 1200      # hard safety cap (covers very large collections)

    def __init__(
        self,
        io,
        *,
        on_log=None,
        on_progress=None,
        clock=time.monotonic,
        sleeper=time.sleep,
        stop_event=None,
        auto_focus: bool = True,
        max_minutes: float = 45.0,    # safety upper bound; ends early on "done" at the grid bottom
    ):
        self.io = io
        self.on_log = on_log or (lambda m: None)
        self.on_progress = on_progress or (lambda r: None)
        self.clock = clock
        self.sleeper = sleeper
        self._stop = stop_event
        self.auto_focus = auto_focus
        self.max_minutes = float(max_minutes)
        self.results: list[SurveyResult] = []
        self.owned_count = 0
        self._seen: set[str] = set()
        self._refocus_logged = False

    def _stopped(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    def _ensure_focus(self) -> bool:
        if self.io.focused():
            return True
        if self.auto_focus and hasattr(self.io, "activate"):
            if not self._refocus_logged:
                self.on_log("统计未拥有：Forza 不在前台,正自动切回(按停止可中止)。")
                self._refocus_logged = True
            self.io.activate()
            self.sleeper(0.4)
        return self.io.focused()

    def _record(self, name: str, kind: str, methods: list) -> None:
        if name in self._seen:
            return
        self._seen.add(name)
        res = SurveyResult(name=name, kind=kind, methods=methods)
        self.results.append(res)
        if kind == OBTAIN_REWARD:
            how = METHOD_REWARD
        elif kind == OBTAIN_BUY:
            how = "/".join(methods) if methods else METHOD_AUTOSHOW
        else:
            how = "未知"
        self.on_log(f"统计未拥有：{name} ← {how}（已统计 {len(self.results)} 辆未拥有）")
        self.on_progress(res)

    def run(self) -> str:
        """Survey the whole grid one focused-row at a time, scrolling down. Returns a stop reason.

        Each iteration reads the grid, processes every UN-OWNED card in the CURSOR's row (aligning
        to each via the IO, pressing 购买, reading + classifying the popup, dismissing with A), then
        steps down to the next row. Ends when stepping down no longer advances (bottom), or when the
        row's cars repeat (a safety backstop)."""
        self.on_log("统计未拥有车辆启动：请先停在『车辆收藏』网格页(收集簿→旅行家→车辆收藏)。只读不购买。")
        started = self.clock()
        if not self._ensure_focus():
            return "not_focused"
        self.io.pin_to_top()                     # scroll to top-left for a clean start

        prev_sig = None
        empty = 0
        rows = 0
        while not self._stopped() and rows < self.MAX_STEPS:
            rows += 1
            if (self.clock() - started) / 60.0 >= self.max_minutes:
                self.on_log("统计未拥有：到达时间上限,结束。")
                return "max_minutes"
            if not self._ensure_focus():
                return "not_focused"

            gv = self.io.read()
            if not gv.on_grid:
                empty += 1
                if empty >= 6:
                    self.on_log("统计未拥有：已离开『车辆收藏』网格页,结束。")
                    return "left_grid"
                self.sleeper(0.3)
                continue
            if gv.focused is None:
                empty += 1
                if empty >= 8:
                    return "no_focus"
                self.sleeper(0.2)
                continue
            empty = 0

            fr = gv.focused[0]
            cells = [gv.cells.get((fr, c)) for c in range(5)]
            sig = tuple((c.name if c and c.name else "") for c in cells)
            if prev_sig is not None and sig == prev_sig:
                self.on_log(
                    f"统计未拥有：已扫到底部(共 {len(self.results)} 辆未拥有 / "
                    f"约 {self.owned_count} 辆已拥有)。"
                )
                return "done"
            prev_sig = sig

            for c in range(5):
                if self._stopped():
                    break
                cell = cells[c]
                if not cell or not cell.name or cell.name in self._seen:
                    continue
                if cell.placeholder:
                    if self.io.move_to_col(fr, c):
                        self.io.press("start")           # 购买 (Menu/≡) -> obtain-method popup
                        text = self.io.popup_text()
                        self.io.press("a")               # 取消/确定 -> back to grid (never buys)
                        kind, methods = classify_obtain(text)
                        self._record(cell.name, kind, methods)
                    else:
                        self.on_log(f"统计未拥有：无法对齐到第 {c + 1} 列,跳过 {cell.name}。")
                else:
                    self._seen.add(cell.name)
                    self.owned_count += 1

            if not self.io.next_row():
                self.on_log(
                    f"统计未拥有：已扫到底部(共 {len(self.results)} 辆未拥有 / "
                    f"约 {self.owned_count} 辆已拥有)。"
                )
                return "done"
            self.sleeper(0.05)
        if self._stopped():
            return "stopped"
        return "max_rows"

    def summary(self) -> dict:
        """Aggregate the results into report buckets keyed by obtain method."""
        buckets: dict[str, list] = {}
        for r in self.results:
            keys = r.methods if (r.kind != OBTAIN_UNKNOWN and r.methods) else ["未知"]
            for k in keys:
                buckets.setdefault(k, []).append(r.name)
        return {
            "total_unowned": len(self.results),
            "owned_seen": self.owned_count,
            "by_method": buckets,
        }


def format_report(summary: dict) -> str:
    """Human-readable zh report from summary()."""
    lines = []
    lines.append(f"未拥有车辆统计：共 {summary['total_unowned']} 辆未拥有")
    by = summary.get("by_method", {})
    # stable, friendly ordering
    order = [METHOD_AUTOSHOW, METHOD_WHEELSPIN, METHOD_REWARD]
    keys = [k for k in order if k in by] + [k for k in by if k not in order]
    for k in keys:
        cars = by[k]
        lines.append("")
        lines.append(f"【{k}】{len(cars)} 辆")
        for name in cars:
            lines.append(f"  · {name}")
    return "\n".join(lines)


# Grid banner / prompt markers that only appear on the 车辆收藏 grid (used to confirm we are on it).
_GRID_MARKERS_TITLE = "车辆收藏"
_GRID_MARKERS_PROMPT = ("制造商", "购买")
_POPUP_MARKERS = ("可通过以下途径获得", "作为奖励出现", "是否要", "季节性赛事", "嘉年华游戏列表")


class UnownedSurveyIO:
    """Real game-facing IO for the survey: OUR recognizer (frame + OCR) for sensing + the virtual
    gamepad for input. Foreground-only, read-only capture, no injection. The collection grid has no
    recognizer tag, so this senses the grid from the frame itself (see module docstring)."""

    def __init__(
        self,
        recognizer,
        pad,
        *,
        title: str = "Forza",
        on_log=None,
        sleep=time.sleep,
        tap_hold: float = 0.12,
        settle: float = 0.5,
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

    def _stopped(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    def _dbg(self, msg: str) -> None:
        if self.verbose:
            self.on_log(msg)

    # -- foreground helpers (mirror UnownedBuyIO) -----------------------------
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

    def press(self, name: str) -> None:
        from gamepad import BUTTON_NAMES
        import random
        btn = {"start": "start", "menu": "start"}.get(name, name)
        if btn in BUTTON_NAMES:
            self.pad.tap(btn, hold=self.tap_hold)
        self._sleep(self.settle + random.uniform(0.0, 0.1))

    # -- sensing --------------------------------------------------------------
    def _capture(self):
        snap = self.recognizer.capture(full_ocr=True, region_ocr=False, skip_smart=True)
        self._last_text = " | ".join(str(getattr(it, "text", "")) for it in snap.ocr_items)
        return snap

    @staticmethod
    def _arr(frame):
        try:
            import numpy as np
            a = np.frombuffer(frame.bgra, dtype=np.uint8).reshape((frame.height, frame.width, 4))
            return a[:, :, 2::-1].copy()           # BGRA -> RGB
        except Exception:
            return None

    def _on_grid(self, text: str) -> bool:
        t = text or ""
        if any(m in t for m in _POPUP_MARKERS):    # a popup is up -> not the bare grid
            return False
        if _GRID_MARKERS_TITLE in t:
            return True
        return all(m in t for m in _GRID_MARKERS_PROMPT)

    def read(self) -> GridView:
        snap = self._capture()
        text = self._last_text
        on_grid = self._on_grid(text)
        cells: dict = {}
        focus = None
        arr = self._arr(snap.frame) if on_grid else None
        if on_grid and arr is not None:
            for r in range(3):
                for c in range(5):
                    cells[(r, c)] = Cell(
                        name=read_cell_name(snap.ocr_items, r, c),
                        placeholder=is_placeholder_cell(arr, r, c),
                    )
            focus = focused_cell(arr)
        self._dbg(f"  [看] on_grid={on_grid} focus={focus}")
        return GridView(on_grid=on_grid, focused=focus, cells=cells, text=text)

    def pin_to_top(self) -> None:
        for _ in range(7):
            if self._stopped():
                return
            self.press("dpad_up")
        for _ in range(5):
            if self._stopped():
                return
            self.press("dpad_left")

    def move_to_col(self, row: int, col: int, *, max_tries: int = 6) -> bool:
        """Align the cursor to (row, col) within the current row, verifying via the focus ring."""
        for _ in range(max_tries):
            if self._stopped():
                return False
            gv = self.read()
            if gv.focused is None:
                self.press("dpad_left")            # nudge to re-acquire a ring
                continue
            _, fc = gv.focused
            if fc == col:
                return True
            self.press("dpad_right" if col > fc else "dpad_left")
        gv = self.read()
        return gv.focused is not None and gv.focused[1] == col

    def popup_text(self, timeout: float = 4.0) -> str:
        """Wait for the 购买 popup, return its full OCR text (or the last text seen on timeout)."""
        end = time.monotonic() + timeout
        last = ""
        while time.monotonic() < end:
            if self._stopped():
                break
            self._capture()
            t = self._last_text
            last = t
            if any(m in t for m in _POPUP_MARKERS):
                return t
            self._sleep(0.25)
        return last

    def next_row(self) -> bool:
        """Press down once; True if the view advanced (the focused car changed)."""
        before = self.read()
        before_name = before.cells.get(before.focused).name if before.focused else ""
        self.press("dpad_down")
        after = self.read()
        if after.focused is None:
            return False
        after_name = after.cells.get(after.focused).name if after.focused else ""
        return bool(after_name and after_name != before_name)
