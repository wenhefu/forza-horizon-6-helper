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
        stop_event=None,
    ):
        self.recognizer = recognizer
        self.pad = pad
        self.dry_run = dry_run
        self.keep_per_model = keep_per_model
        self.on_log = on_log or (lambda message: None)
        self._sleep = sleep
        self.walk_steps = walk_steps
        self._stop = stop_event
        self._filter_on = False

    def _stopped(self) -> bool:
        return self._stop is not None and self._stop.is_set()

    def _look(self):
        # full-res OCR: downscaling mis-read the 选择操作 menu rows (从车库移除 was missed),
        # which is unacceptable on a destructive flow. Reliability over the ~30% speed.
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

    def _ensure_my_vehicles(self, attempts=6):
        """Reach the My Vehicles grid. RELIABLE subset only: already on the grid (done),
        the 车辆 tab (-> 更换车辆 -> A), or a dismissable modal (B, e.g. controller modal /
        移动至嘉年华). Any OTHER start state bails -- blind tab-cycling could wander into the
        autoshow and trigger stray prompts. So: start from My Vehicles or the 车辆 tab."""
        for _ in range(attempts):
            screen, _, _ = self._look()
            if screen == "eventlab_my_cars":
                return True
            if screen in ("controller_disconnected", "modal_warning"):
                self._tap("b", after=0.8)          # dismiss a stray modal, then re-check
            elif screen == "pause_vehicle_entry":
                self._tap("dpad_up", after=0.4)
                self._tap("dpad_up", after=0.4)    # reach 更换车辆 (top tile)
                self._tap("a", after=1.3)          # open My Vehicles grid
            else:
                return False                       # unknown start -> bail, don't wander
        return self._look()[0] == "eventlab_my_cars"

    def run(self):
        if not self._ensure_my_vehicles():
            self.on_log("卖重复车：没能进入“我的车辆”网格。请先打开 车辆→更换车辆。")
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
        # Navigate to 从车库移除车辆. FAST path: the menu opens on 上车 and 从车库移除车辆 is
        # the 5th row, so settle + blind DpadDown ×4 lands on it; verify with ONE FULL-RES
        # read (full-res is essential here -- downscaling mis-reads these rows, the bug we
        # reverted). If the blind guess is off (an absorbed input), fall back to read-every-
        # step. ~1 read vs ~5; worst case still aborts safely on the confirm-dialog gate.
        self._sleep(0.3)
        for _ in range(4):
            self._tap("dpad_down", after=0.22)
        _, sel, _ = self._look()
        if "从车库移除" not in sel:
            for _ in range(6):
                self._tap("dpad_down", after=0.3)
                _, sel, _ = self._look()
                if "从车库移除" in sel:
                    break
        if "从车库移除" not in sel:
            self.on_log("    ⚠ 菜单里没定位到“从车库移除车辆”，退出。")
            self._tap("b", after=0.6)
            return "abort_no_target"
        self._tap("a", after=0.8)
        # Poll for the remove-confirm dialog (it can take a moment to render).
        confirmed = False
        for _ in range(4):
            _, _, ocr2 = self._look()
            if detect_remove_confirm(ocr2)["visible"]:
                confirmed = True
                break
            self._sleep(0.25)
        if not confirmed:
            self.on_log("    ⚠ 没确认到“从车库移除”对话框，放弃这一辆，退出菜单。")
            self._tap("b", after=0.6)
            return "abort_no_confirm"
        # confirm dialog defaults to 不(No): DpadDown -> 嗯(Yes) -> A
        self._tap("dpad_down", after=0.4)
        self._tap("a", after=1.3)
        return "sold"

    def run_sell(self, max_sell=1, target_name=None):
        """Remove up to max_sell duplicate cars. If target_name is given, only cars whose
        focused name contains it are touched (e.g. "22B"), so other duplicated models are
        left alone. Favorited / currently-driving cars are always skipped."""
        if not self._ensure_my_vehicles():
            self.on_log("卖重复车[真删]：没能进入“我的车辆”网格。请先打开 车辆→更换车辆。")
            return 0
        if not self._toggle_duplicates_filter():
            return 0
        self._filter_on = True
        scope = f"，只卖含“{target_name}”的车" if target_name else "（所有重复车型）"
        self.on_log(f"卖重复车[真删]：已开“重复项”，最多删 {max_sell} 辆{scope}（跳过收藏/正在驾驶的）。")
        sold, attempts, idle = 0, 0, 0
        while sold < max_sell and idle < 12 and not self._stopped():
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
                self._sleep(0.7)  # grid re-renders; focus shifts to the next card
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
