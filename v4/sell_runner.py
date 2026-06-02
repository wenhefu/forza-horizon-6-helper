"""Duplicate-car scanner/seller via the game-native 重复项 (Duplicates) filter.

Phase B of the super-assistant. `run()` is a READ-ONLY dry-run (enable 重复项, sweep,
report). `run_sell(max_sell)` actually removes duplicates, with layered safety so the
farm 22B is never touched:
  1. Only cars whose 选择操作 menu offers 从车库移除车辆 AND are not favorited are sellable
     (`detect_vehicle_action_menu().sellable`). The currently-DRIVING car has no remove
     option (game-native), and favorited cars are skipped.
  2. After navigating to 从车库移除车辆 and pressing A, it VERIFIES the
     '从车库移除车辆 / 确定要移除' confirm dialog before pressing 嗯 -- a mis-navigated menu
     can never confirm a deletion.
  3. max_sell caps how many are removed per run.
"""
import time
from collections import Counter

from gamepad import BUTTON_NAMES
from v3.buying_ui import detect_remove_confirm, detect_vehicle_action_menu
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

    # ----- actual removal (DESTRUCTIVE, layered-safe) -------------------------

    def _menu_state(self):
        """Open the focused card's 选择操作 menu and read its state."""
        self._tap("a", after=1.0)
        _, _, ocr = self._look()
        return detect_vehicle_action_menu(ocr)

    def sell_focused_card(self):
        """Try to remove the focused card. NEVER removes a favorited or currently-driving
        car, and verifies the 从车库移除 confirm dialog before pressing 嗯."""
        menu = self._menu_state()
        if not menu["visible"]:
            self._tap("b", after=0.6)
            return "no_menu"
        if not menu["sellable"]:
            reason = "收藏" if menu["favorited"] else ("在驾驶/无移除项" if not menu["has_remove"] else "未知")
            self._tap("b", after=0.6)  # cancel; card untouched
            return f"skip_protected({reason})"
        # sellable normal-car menu order: 上车 / 添加至收藏 / 查看车辆 / 查看历史记录 /
        # 从车库移除车辆 / 举报并移除涂装. Opens on 上车 -> DpadDown ×4 -> 从车库移除车辆.
        for _ in range(4):
            self._tap("dpad_down", after=0.3)
        self._tap("a", after=1.1)
        _, _, ocr2 = self._look()
        if not detect_remove_confirm(ocr2)["visible"]:
            self.on_log("    ⚠ 没确认到“从车库移除”对话框，放弃这一辆，退出菜单。")
            self._tap("b", after=0.5)
            self._tap("b", after=0.5)
            return "abort_no_confirm"
        # confirm dialog defaults to 不(No): DpadDown -> 嗯(Yes) -> A
        self._tap("dpad_down", after=0.4)
        self._tap("a", after=1.3)
        return "sold"

    def run_sell(self, max_sell=1, target_name=None):
        """Remove up to max_sell duplicate cars. If target_name is given, only cars whose
        focused name contains it are touched (e.g. "22B"), so other duplicated models are
        left alone. Favorited / currently-driving cars are always skipped."""
        screen, _, _ = self._look()
        if screen != "eventlab_my_cars":
            self.on_log(f"卖重复车[真删]：当前不在“我的车辆”网格（screen={screen}）。请先打开 车辆→更换车辆。")
            return 0
        if not self._toggle_duplicates_filter():
            return 0
        self._filter_on = True
        scope = f"，只卖含“{target_name}”的车" if target_name else "（所有重复车型）"
        self.on_log(f"卖重复车[真删]：已开“重复项”，最多删 {max_sell} 辆{scope}（跳过收藏/正在驾驶的）。")
        sold, attempts, idle = 0, 0, 0
        while sold < max_sell and idle < 8:
            attempts += 1
            screen, name, _ = self._look()
            if screen != "eventlab_my_cars":
                self.on_log("  网格已变（可能该车型重复清空），停止。")
                break
            if target_name and target_name not in name:
                self.on_log(f"  跳过(非目标车型: {name})")
                self._tap("dpad_right", after=0.5)
                idle += 1
                continue
            result = self.sell_focused_card()
            self.on_log(f"  第{attempts}次({name})：{result}")
            if result == "sold":
                sold += 1
                idle = 0
                self._sleep(1.0)  # grid re-renders; focus shifts to the next card
            elif result.startswith("skip_protected"):
                self._tap("dpad_right", after=0.5)  # next card, try again
                idle += 1
            else:
                break  # no_menu / abort -> stop, stay safe
        self.on_log(f"卖重复车[真删]：本次共删 {sold} 辆。")
        if self._filter_on and self._toggle_duplicates_filter():
            self._filter_on = False
            self.on_log("卖重复车：已关闭“重复项”，恢复原状。")
        return sold
