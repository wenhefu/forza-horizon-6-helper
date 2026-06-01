"""Run the experimental V5 event-driven navigation to the EventLab race menu.

Usage (keep Forza in the foreground on a menu/free-roam page, then):
    python v5_nav_launcher.py
    python v5_nav_launcher.py --goal race_menu --max-seconds 300
    python v5_nav_launcher.py --no-engine        # skip dxcam, use synchronous capture

It navigates the current screen toward the goal with the V5 event-driven reactor
(no fixed settle sleeps) and prints each step + timing. It only sends normal
virtual-pad input and requires the game in the foreground (no fake-focus).
"""
import argparse
import logging

import config
from v5.nav_runner import V5Navigator


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="V5 event-driven navigation (experimental).")
    parser.add_argument("--title", default=getattr(config, "GAME_TITLE", "Forza"))
    parser.add_argument("--goal", default="race_menu", help="target screen id (default: race_menu)")
    parser.add_argument("--no-engine", action="store_true", help="disable dxcam continuous capture")
    parser.add_argument("--allow-background", action="store_true", help="do not require the game foreground")
    parser.add_argument("--max-seconds", type=float, default=600.0)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    nav = V5Navigator(
        title=args.title,
        goal=args.goal,
        on_log=print,
        require_foreground=not args.allow_background,
        use_capture_engine=not args.no_engine,
        max_seconds=args.max_seconds,
    )
    nav.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
