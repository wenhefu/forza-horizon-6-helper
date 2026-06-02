"""Duplicate-car scanner/seller — READ-ONLY dry-run by default.

Phase B of the super-assistant. Uses the game-native 重复项 (Duplicates) filter so it
never scans the whole garage: enable the filter, sweep the (small) duplicate set with
DpadRight reading each focused car name, and report the duplicated models via the vetted
v4.sell_planner. Selling is GATED behind dry_run=False and is not implemented here yet --
it is destructive and needs the per-card 当前车辆/收藏 read + a sell-and-observe loop
(see docs/SUPER_ASSISTANT.md). The dry-run is read-only, so it is safe to run/iterate.
"""
import time
from collections import Counter

from gamepad import BUTTON_NAMES
from v4.sell_planner import VehicleCard, summarize_plan


def distinct_models(names):
    """Ordered distinct car names from a sweep (dups share names; this is the reliable
    signal -- the SET of duplicated models, independent of wrap/termination)."""
    seen = []
    for name in names:
        n = (name or "").strip()
        if n and n not in seen:
            seen.append(n)
    return seen


class SellDuplicatesRunner:
    def __init__(
        self,
        recognizer,
        pad,
        *,
        dry_run: bool = True,
        keep_per_model: int = 1,
        on_log=None,
        sleep=time.sleep,
        walk_steps: int = 50,
    ):
        self.recognizer = recognizer
        self.pad = pad
        self.dry_run = dry_run
        self.keep_per_model = keep_per_model
        self.on_log = on_log or (lambda message: None)
        self._sleep = sleep
        self.walk_steps = walk_steps
        self._filter_on = False

    def _look(self):
        snap = self.recognizer.capture(full_ocr=True, region_ocr=True)
        u = snap.v3
        ocr = " | ".join(str(getattr(it, "text", "")) for it in snap.ocr_items)
        return str(getattr(u, "screen", "") or ""), str(getattr(u, "selected_item", "") or ""), ocr

    def _tap(self, button, after=0.7):
        if button in BUTTON_NAMES:
            self.pad.tap(button, hold=0.12)
        self._sleep(after)

    def _toggle_duplicates_filter(self):
        """Open 筛选, focus 重复项 (dpad_down ×2 from 收藏), toggle it, close."""
        self._tap("y", after=1.0)
        screen, _, _ = self._look()
        if screen != "eventlab_filter":
            self.on_log("卖重复车：按 Y 没进入筛选弹窗，放弃。")
            return False
        self._tap("dpad_down", after=0.5)
        self._tap("dpad_down", after=0.5)
        self._tap("a", after=0.6)   # 切换 重复项
        self._tap("b", after=1.1)   # back to grid
        return True

    def scan(self):
        """Bounded DpadRight sweep of the duplicate-filtered grid → list of focused names.

        First walk to the top-left so the sweep covers a full row from its start (the
        caller may have left the cursor anywhere). Dup copies share names, so we just
        collect the focused name per step; distinct_models() yields the duplicated models.
        """
        for _ in range(4):
            self._tap("dpad_up", after=0.25)
        for _ in range(16):
            self._tap("dpad_left", after=0.22)
        names = []
        for _ in range(self.walk_steps):
            screen, name, _ = self._look()
            if screen != "eventlab_my_cars" or not name:
                break
            names.append(name)
            self._tap("dpad_right", after=0.4)
        return names

    def run(self):
        screen, _, _ = self._look()
        if screen != "eventlab_my_cars":
            self.on_log(f"卖重复车：当前不在“我的车辆”网格（screen={screen}）。请先打开 车辆→更换车辆。")
            return None

        if not self._toggle_duplicates_filter():
            return None
        self._filter_on = True
        self.on_log("卖重复车：已开启“重复项”筛选，开始扫描。")

        names = self.scan()
        models = distinct_models(names)
        counts = Counter(n.strip() for n in names if n and n.strip())
        capped = len(names) >= self.walk_steps
        self.on_log(f"卖重复车[空跑]：扫描 {len(names)} 张卡，发现 {len(models)} 个重复车型：")
        for model in models:
            self.on_log(f"  · {model} × {counts[model]}")
        if capped:
            self.on_log(
                f"卖重复车[空跑]：本次扫到上限 {self.walk_steps} 张（像 22B 这种大量重复会更多，"
                "未数到底）。"
            )
        self.on_log(
            f"卖重复车[空跑]：若执行,将每个车型留 {self.keep_per_model} 辆、卖掉多余的"
            "（绝不卖当前车/收藏）。本次为只读空跑，未卖出任何车。"
        )

        # restore: toggle the filter back off so the garage view is unchanged
        if self._filter_on:
            if self._toggle_duplicates_filter():
                self._filter_on = False
                self.on_log("卖重复车：已关闭“重复项”筛选，恢复原状。")

        return {"swept": len(names), "models": models}
