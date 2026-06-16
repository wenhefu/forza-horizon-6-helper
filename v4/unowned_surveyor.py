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

OBTAIN_BUY = "buy"        # 车展 available -> the popup offers 是否要从车展购买 (取消/确认)
OBTAIN_INFO = "info"      # has obtain methods but NOT 车展 -> info + single 确定 (can't buy directly)
OBTAIN_REWARD = "reward"  # reward-only: 季节赛事/嘉年华游戏列表
OBTAIN_BARNFIND = "barnfind"
OBTAIN_UNKNOWN = "unknown"

# Canonical obtain-method labels (zh) the report groups by. Derived from a LIVE corpus of 139 cars'
# 购买 popups (logs/购买文案语料.jsonl) -- the real text is far richer than the first two samples.
METHOD_AUTOSHOW = "车展"
METHOD_WHEELSPIN = "抽奖"
METHOD_REWARD = "季节赛事/嘉年华奖励"
METHOD_BARNFIND = "谷仓车(寻车任务)"
METHOD_MASTERY = "车辆专精树"
METHOD_STORE = "商店/DLC"

# Collection-book ("收集簿") reward categories seen in the corpus; matched as substrings so OCR noise
# (smart quotes, a split 类/别) still resolves. Longer names first so e.g. 地平线传奇赛 wins over 地平线传奇.
_COLLECTION_CATS = (
    "地平线传奇赛", "地平线宣传活动", "地平线传奇", "奖励广告牌", "车辆收藏",
    "危险标志", "测速区间", "一日游", "车库", "漂移区", "限速",
)

_OBTAIN_RE = re.compile(r"获得[:：]?\s*(.+?)(?:是否要|作为奖励|。|$)", re.S)

# Phrases that only appear inside a 购买 popup (never on the bare grid) -- used to confirm a popup is
# actually open before we press a dismiss button (so we never 选择 into a car that showed no popup).
# Includes the standard modal BUTTON words (确定/确认/取消) so even a never-seen-before popup template
# is still recognized as a modal and gets dismissed -- the bare grid prompt bar has none of these
# (it shows 选择/返回/已排序/制造商/购买).
POPUP_MARKERS = (
    "可通过以下途径获得", "作为奖励出现", "是否要", "季节性赛事", "嘉年华游戏列表",
    "购买这辆车", "确定", "确认", "取消",
)


def is_popup(text: str) -> bool:
    t = text or ""
    return any(m in t for m in POPUP_MARKERS)


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


def _method_label(tok: str) -> str:
    """Map one raw obtain-method token to a canonical label (substring matching survives OCR noise)."""
    if "车展" in tok or tok.strip(" 、，,。\"'“”「」") == "车":   # bare "车" = OCR-truncated 车展
        return METHOD_AUTOSHOW
    if "抽奖" in tok or "转盘" in tok:
        return METHOD_WHEELSPIN
    if "专精" in tok:
        return METHOD_MASTERY
    if "商店" in tok or "附加内容" in tok or "DLC" in tok or "dlc" in tok:
        return METHOD_STORE
    if "嘉年华" in tok or "季节" in tok:
        return METHOD_REWARD
    if "收集簿" in tok or "收集薄" in tok:
        for cat in _COLLECTION_CATS:
            if cat in tok:
                return f"收集簿·{cat}"
        return "收集簿奖励"
    return tok.strip(" 、，,。\"'“”‘’「」")


def classify_obtain(text: str):
    """Classify a 购买 popup's raw OCR text -> (kind, [canonical method labels]).

    kind in buy|info|reward|barnfind|unknown. `methods` is the de-duplicated list of canonical labels
    the report groups by. Built + validated against the live 139-car corpus."""
    t = text or ""
    # Barn-find / wreck. Two live variants:
    #   "四处探索，寻找关于该废弃车辆下落的线索..."  and  "听说这辆车被人遗弃在车房里..."
    if ("废弃车辆" in t or "车房" in t or "遗弃" in t or ("线索" in t and "寻找" in t)):
        return OBTAIN_BARNFIND, [METHOD_BARNFIND]
    methods: list[str] = []
    m = _OBTAIN_RE.search(t)
    if m:
        raw = m.group(1).replace("|", " ")              # OCR splits the list across | -- rejoin
        for tok in re.split(r"[，,、/]+", raw):
            tok = tok.strip()
            if not tok:
                continue
            methods.append(_method_label(tok))
    # The reward note can co-occur with a 抽奖 method (single-确定 popup) -- add it too.
    if ("作为奖励出现" in t) or ("嘉年华游戏列表" in t) or ("季节赛事" in t) or ("季节性赛事" in t):
        methods.append(METHOD_REWARD)
    # de-dup, preserve order, drop empties
    seen = set()
    methods = [x for x in methods if x and not (x in seen or seen.add(x))]
    if not methods:
        return OBTAIN_UNKNOWN, []
    kind = OBTAIN_BUY if METHOD_AUTOSHOW in methods else (
        OBTAIN_REWARD if methods == [METHOD_REWARD] else OBTAIN_INFO)
    return kind, methods


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
        collect_all: bool = False,    # data-collection: press 购买 on EVERY car (owned too) to log its raw 文案
        on_corpus=None,               # callback(name, placeholder, text) for each car in collect_all mode
    ):
        self.io = io
        self.on_log = on_log or (lambda m: None)
        self.on_progress = on_progress or (lambda r: None)
        self.collect_all = bool(collect_all)
        self.on_corpus = on_corpus
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
        how = "/".join(methods) if methods else "未知"
        self.on_log(f"统计未拥有：{name} ← {how}（已统计 {len(self.results)} 辆未拥有）")
        self.on_progress(res)

    NO_PROGRESS_LIMIT = 14   # consecutive already-seen cells => the whole grid is covered (at bottom)

    def run(self) -> str:
        """Survey the whole grid by walking the cursor cell-by-cell in a SNAKE (boustrophedon):
        right across a row, down, left across the next, down, ... It does NOT scroll to the top first
        -- it starts from wherever the cursor is and, because the grid WRAPS (down past the bottom
        loops to the top -- verified live), it laps the entire grid and stops once it keeps re-seeing
        already-catalogued cars (every visited car is remembered). At every step it classifies the
        cursor's FOCUSED cell -- the focus ring is ground truth and the focused card is clearest to
        read -- and processes an un-owned card IN PLACE, so it cannot skip a cell."""
        self.on_log("统计未拥有车辆启动：请先停在『车辆收藏』网格页(收集簿→旅行家→车辆收藏)。只读不购买。")
        started = self.clock()
        if not self._ensure_focus():
            return "not_focused"
        # No pin-to-top: start from the current view (the grid wraps, so the snake covers everything
        # and terminates when it laps back to seen cars -- avoids the janky initial scroll).

        direction = 1                            # +1 = rightward across a row, -1 = leftward
        last_action = None                       # "H" = last move was horizontal, "D" = down
        prev_pos = None                          # (row, col) before the last move
        no_progress = 0
        stuck_h = 0
        empty = 0
        recover = 0
        steps = 0
        while not self._stopped() and steps < self.MAX_STEPS:
            steps += 1
            if (self.clock() - started) / 60.0 >= self.max_minutes:
                self.on_log("统计未拥有：到达时间上限,结束。")
                return "max_minutes"
            if not self._ensure_focus():
                return "not_focused"

            gv = self.io.read()
            if not gv.on_grid:
                # Recover from a stray modal that the virtual pad's flicker leaves on top of the grid:
                # the controller-disconnect modal, or a buy/reward popup left open by a prior run.
                # A dismisses both (确定 / 取消-focused) and returns to the grid -- never a blind press
                # on the bare grid (that path falls through to the empty-counter below).
                t = gv.text or ""
                if (("控制器" in t) or ("重新连接" in t) or is_popup(t)) and recover < 10:
                    recover += 1
                    self.io.press("a")
                    self.sleeper(0.4)
                    continue
                empty += 1
                if empty >= 6:
                    self.on_log("统计未拥有：已离开『车辆收藏』网格页,结束。")
                    return "left_grid"
                self.sleeper(0.3)
                continue
            recover = 0
            empty = 0
            if gv.focused is None:
                self.io.press("dpad_left")       # nudge to re-acquire the focus ring
                self.sleeper(0.1)
                continue

            fr, fc = gv.focused
            cell = gv.cells.get((fr, fc))
            name = cell.name if cell else ""

            # --- classify the FOCUSED cell (ground truth, clearest to read) ------------------
            is_new = bool(name) and name not in self._seen
            if is_new:
                if cell.placeholder or self.collect_all:
                    self._survey_focused_cell(cell)   # presses 购买 + records / counts; adds to _seen
                else:
                    self._seen.add(name)
                    self.owned_count += 1
                no_progress = 0
            else:
                no_progress += 1
                if no_progress >= self.NO_PROGRESS_LIMIT:
                    self.on_log(
                        f"统计未拥有：已扫完(共 {len(self.results)} 辆未拥有 / "
                        f"约 {self.owned_count} 辆已拥有)。"
                    )
                    return "done"

            # --- detect a horizontal press that didn't move (a partial row's edge) -----------
            if last_action == "H" and prev_pos == (fr, fc):
                stuck_h += 1
            else:
                stuck_h = 0
            prev_pos = (fr, fc)

            # --- advance ONE cell in snake order --------------------------------------------
            nxt = fc + direction
            if 0 <= nxt <= 4 and stuck_h < 2:
                self.io.press("dpad_right" if direction > 0 else "dpad_left")
                last_action = "H"
            else:                                # row edge (or stuck) -> drop a row, reverse
                self.io.press("dpad_down")
                direction = -direction
                last_action = "D"
                stuck_h = 0
        if self._stopped():
            return "stopped"
        return "max_steps"

    def _survey_focused_cell(self, cell: Cell) -> None:
        """The cursor is already ON this cell. Press 购买, read + classify the popup, dismiss (A).
        Never buys. Adds the name to _seen (via _record for un-owned, or directly for owned)."""
        self.io.press("start")                   # 购买 (Menu/≡) -> obtain-method popup
        text = self.io.popup_text()
        if is_popup(text):
            self.io.press("a")                   # 取消/确定 -> back to grid (never buys)
        else:
            # No popup (a truly-owned, non-buyable car) -> do NOT press A (it would 选择 into it).
            self.on_log(f"统计未拥有：{cell.name} 未弹出购买窗(可能已拥有),跳过。")
        if self.collect_all and self.on_corpus:
            try:
                self.on_corpus(cell.name, cell.placeholder, text)
            except Exception:
                pass
        if cell.placeholder:
            kind, methods = classify_obtain(text)
            if kind == OBTAIN_UNKNOWN:
                self.on_log(f"统计未拥有[未知文案] {cell.name}: {(text or '')[:90]}")
            self._record(cell.name, kind, methods)    # appends result + adds to _seen
        else:
            self._seen.add(cell.name)
            self.owned_count += 1

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
    # stable, friendly ordering (common methods first, 收集簿·* and any novel labels after)
    order = [METHOD_AUTOSHOW, METHOD_WHEELSPIN, METHOD_REWARD,
             METHOD_BARNFIND, METHOD_MASTERY, METHOD_STORE]
    keys = [k for k in order if k in by] + sorted(k for k in by if k not in order)
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
_POPUP_MARKERS = POPUP_MARKERS   # shared with the surveyor's popup gate (defined near classify_obtain)


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
        """Scroll all the way to the TRUE top, then go to the leftmost column. Detects the top by the
        VISIBLE PLACEHOLDER PATTERN going stable (the grid can't scroll up) -- the gray-placeholder
        mask is deterministic, unlike the OCR names which jitter and would never settle. Up-presses
        are fast taps (no per-step settle); if some are dropped the pattern just keeps changing, so it
        self-corrects. A fixed count is NOT enough for a tall collection -- under-scrolling silently
        skips the top rows (the bug that made the survey miss cars)."""
        from gamepad import BUTTON_NAMES

        last_pat = None
        same = 0
        for _ in range(45):                      # cap (~360 up-presses of headroom)
            if self._stopped():
                break
            for _ in range(8):                   # fast bulk up-taps (no per-press recognition)
                if "dpad_up" in BUTTON_NAMES:
                    self.pad.tap("dpad_up", hold=self.tap_hold)
                self._sleep(0.1)
            self._sleep(0.3)                     # let the scroll settle, then read once
            gv = self.read()
            if not gv.on_grid:
                continue
            pat = tuple(
                bool(gv.cells.get((r, c)) and gv.cells[(r, c)].placeholder)
                for r in range(3) for c in range(5)
            )
            if pat == last_pat:
                same += 1
                if same >= 1:                    # stable across two reads -> at the top
                    break
            else:
                same = 0
                last_pat = pat
        for _ in range(6):
            if self._stopped():
                return
            self.press("dpad_left")

    def move_to_col(self, row: int, col: int, *, max_tries: int = 4) -> bool:
        """Align the cursor to (row, col) within the current row, verifying via the focus ring.

        Fast path: read the current column once, press the whole delta in one go (no read between --
        dpad presses are reliable with the settle delay), then verify once + a few corrective steps.
        That's ~2-3 captures instead of one-per-press, which dominates the survey's wall-clock."""
        gv = self.read()
        if gv.focused is None:
            self.press("dpad_left")                # nudge to re-acquire a ring
            gv = self.read()
        if gv.focused is None:
            return False
        fc = gv.focused[1]
        if fc == col:
            return True
        btn = "dpad_right" if col > fc else "dpad_left"
        for _ in range(abs(col - fc)):
            if self._stopped():
                return False
            self.press(btn)
        gv = self.read()
        tries = 0
        while gv.focused is not None and gv.focused[1] != col and tries < max_tries:
            tries += 1
            fc2 = gv.focused[1]
            self.press("dpad_right" if col > fc2 else "dpad_left")
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

    def next_row(self, before_name: str | None = None) -> bool:
        """Press down once; True if the view advanced (the focused car changed). When the caller
        already knows the current focused-car name (cursor hasn't moved since its read), pass it as
        before_name to skip the redundant 'before' capture -- the common no-placeholder row case."""
        if before_name is None:
            before = self.read()
            before_name = before.cells.get(before.focused).name if before.focused else ""
        self.press("dpad_down")
        after = self.read()
        if after.focused is None:
            return False
        after_name = after.cells.get(after.focused).name if after.focused else ""
        return bool(after_name and after_name != before_name)
