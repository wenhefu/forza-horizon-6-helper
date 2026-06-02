"""Dry-run scan of duplicate cars (READ-ONLY) via the native 重复项 filter.

Open My Vehicles first (暂停 → 车辆 → 更换车辆), keep Forza foreground, then:
    python sell_launcher.py --auto-focus
It enables 重复项, sweeps the duplicates, prints which models are duplicated, and
restores the filter. It does NOT sell anything (selling is a later, gated step).
Only normal virtual-pad input; requires the game in the foreground.
"""
import argparse
import logging
import time

import config
import focus
from gamepad import Gamepad
from v4.recognizer import V4Recognizer
from v4.sell_runner import SellDuplicatesRunner


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Duplicate-car scan / sell.")
    parser.add_argument("--title", default=getattr(config, "GAME_TITLE", "Forza"))
    parser.add_argument("--auto-focus", action="store_true", help="bring Forza to the foreground first")
    parser.add_argument("--keep", type=int, default=1, help="copies to keep per model (report only)")
    parser.add_argument("--sell", action="store_true", help="ACTUALLY remove duplicates (destructive)")
    parser.add_argument("--max", type=int, default=1, help="with --sell: max cars to remove this run")
    parser.add_argument("--model", default=None, help="with --sell: only remove cars whose name contains this (e.g. 22B)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    if args.auto_focus:
        focus.activate_window(args.title)
        time.sleep(0.6)

    recognizer = V4Recognizer(title=args.title)
    pad = Gamepad()
    time.sleep(0.6)

    # Dismiss a controller-disconnected modal left by a previous run (pad just reconnected).
    for _ in range(3):
        snap = recognizer.capture(full_ocr=True, region_ocr=True)
        if getattr(snap.v3, "screen", "") != "controller_disconnected":
            break
        pad.tap("a", hold=0.12)
        time.sleep(1.0)

    try:
        runner = SellDuplicatesRunner(
            recognizer, pad, dry_run=not args.sell, keep_per_model=args.keep, on_log=print
        )
        if args.sell:
            scope = f"，只卖含“{args.model}”的车" if args.model else ""
            print(f"=== 真删模式：最多删 {args.max} 辆{scope}（跳过收藏/正在驾驶的，删前核对确认框）===")
            runner.run_sell(max_sell=args.max, target_name=args.model)
        else:
            runner.run()
    finally:
        pad.neutral()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
