"""Live launcher / probe for the auction-house sniper (Phase C).

Foreground-only, read-only capture, virtual gamepad -- NO injection. Modes:

  --probe     (default) OCR the CURRENT screen N times and print how the detectors classify
              it. Presses NOTHING. Run this FIRST to verify the detectors against the live
              game before any input.
  --dry-run   Run the snipe loop in DRY-RUN: navigates 选择 -> 车辆详情 -> Down -> Enter and
              VERIFIES it reaches the 买断 confirm, then backs out. NEVER confirms a buy.
  --buy       REAL buying. Buys out up to --max-cars listings (spends credits). Requires this
              explicit flag; dry-run is the default everywhere else.

Pre-set the search in-game first: 拍卖场 -> 搜索拍卖 -> set 型号 + 最高买断价 -> 确认, leaving the
game on the results (拍卖详情) page with listings.

Run unbuffered so progress is visible:  python -u auction_launcher.py --probe
"""
import argparse
import re
import time

import config
import focus
from v3.buying_ui import detect_network_warning
from v4.auction_runner import AuctionIO, AuctionSniper, classify_auction_screen

_PRICE_RE = re.compile(r"\d{1,3}(?:,\d{3})+")


def _log(msg):
    print(time.strftime("[%H:%M:%S] ") + str(msg), flush=True)


def _ocr_text(rec):
    snap = rec.capture(full_ocr=True, region_ocr=True)
    text = " | ".join(str(getattr(it, "text", "")) for it in snap.ocr_items)
    return snap, text


def build_recognizer():
    from v4.recognizer import V4Recognizer
    _log("加载识别模型(YOLO+OCR)…")
    rec = V4Recognizer(title=config.GAME_TITLE)
    _log("识别模型就绪。")
    return rec


def probe(rec, count):
    _log(f"探针模式：只读 OCR ×{count}，不按任何键。请把游戏停在 拍卖场结果页。")
    for i in range(count):
        snap, text = _ocr_text(rec)
        tag = classify_auction_screen(text)
        net = detect_network_warning(text)["visible"]
        price = bool(_PRICE_RE.search(text))
        fg = focus.is_foreground(config.GAME_TITLE)
        sel = getattr(snap.v3, "selected_item", "")
        scr = getattr(snap.v3, "screen", "")
        _log(f"#{i + 1} 前台={fg} 识别={tag} v3屏={scr} 选中={sel!r} 有价格={price} 断网={net}")
        _log(f"     OCR: {text[:200]}")
        time.sleep(0.8)


def dismiss_controller_modal(rec, pad):
    for _ in range(3):
        snap, _ = _ocr_text(rec)
        if getattr(snap.v3, "screen", "") != "controller_disconnected":
            break
        _log("关闭『控制器已断开』提示…")
        pad.tap("a", hold=0.12)
        time.sleep(1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="只读探针，不按键(默认)")
    ap.add_argument("--dry-run", action="store_true", help="空跑：走流程但绝不买")
    ap.add_argument("--buy", action="store_true", help="真买！会花积分")
    ap.add_argument("--count", type=int, default=8, help="探针读屏次数")
    ap.add_argument("--once", action="store_true", help="只跑一次 run_once 就停(首跑用)")
    ap.add_argument("--verbose", action="store_true", help="逐步打印每次读屏/按键")
    ap.add_argument("--max-cars", type=int, default=1)
    ap.add_argument("--max-minutes", type=float, default=20.0)
    args = ap.parse_args()

    mode = "buy" if args.buy else ("dry" if args.dry_run else "probe")
    rec = build_recognizer()

    try:
        focus.activate_window(title_substr=config.GAME_TITLE, on_log=_log)
    except Exception:
        pass
    time.sleep(0.6)

    if mode == "probe":
        probe(rec, args.count)
        return

    from gamepad import Gamepad
    pad = Gamepad()
    time.sleep(0.5)
    dismiss_controller_modal(rec, pad)
    io = AuctionIO(rec, pad, title=config.GAME_TITLE, on_log=_log, verbose=args.verbose)
    sniper = AuctionSniper(
        io,
        dry_run=(mode != "buy"),
        max_cars=args.max_cars,
        max_minutes=args.max_minutes,
        on_log=_log,
    )
    try:
        if mode == "buy":
            _log(f"!!! 真买模式：最多 {args.max_cars} 辆。3 秒后开始，Ctrl+C 取消。")
            time.sleep(3.0)
        if args.once:
            result = sniper.run_once()
            _log(f"单次结束：{result}")
        else:
            result = sniper.run()
            _log(f"结束：{result}（已买 {sniper.bought}，搜索 {sniper.searches} 次）")
    finally:
        try:
            pad.neutral()
        except Exception:
            pass


if __name__ == "__main__":
    main()
