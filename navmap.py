"""Throwaway live nav-mapper: capture the REAL auction re-search navigation (no buying).

Maps 拍卖场landing -> 搜索拍卖 -> 搜寻 -> 确认 -> 结果, logging screen + selected_item + OCR at
each step so the re-search loop can be built on real transitions instead of guesses. Presses
only A / Down and stops at the results screen -- never opens a buy/bid. Run unbuffered."""
import time

import config
import focus
from gamepad import Gamepad
from v4.auction_runner import classify_auction_screen
from v4.recognizer import V4Recognizer


def log(m):
    print(time.strftime("[%H:%M:%S] ") + str(m), flush=True)


def main():
    log("加载识别模型…")
    rec = V4Recognizer(title=config.GAME_TITLE)
    try:
        focus.activate_window(title_substr=config.GAME_TITLE)
    except Exception:
        pass
    time.sleep(0.6)
    pad = Gamepad()
    time.sleep(0.6)

    def look():
        snap = rec.capture(full_ocr=True, region_ocr=True)
        text = " | ".join(str(getattr(it, "text", "")) for it in snap.ocr_items)
        sel = str(getattr(snap.v3, "selected_item", "") or "")
        return classify_auction_screen(text), sel, text

    def tap(b, after=0.8):
        pad.tap(b, hold=0.12)
        time.sleep(after)

    for _ in range(3):  # dismiss controller-disconnected modal
        snap = rec.capture(full_ocr=True, region_ocr=True)
        if getattr(snap.v3, "screen", "") != "controller_disconnected":
            break
        log("关闭『控制器未连接』…")
        pad.tap("a", hold=0.12)
        time.sleep(1.0)

    downs = 0
    try:
        for step in range(14):
            tag, sel, text = look()
            log(f"#{step} 识别={tag} 选中={sel!r}")
            log(f"     OCR: {text[:150]}")
            if tag == "house":
                log("   -> house: 按 A 进入『搜索拍卖』")
                tap("a", after=1.2)
                downs = 0
            elif tag == "search":
                if "确认" in sel:
                    log(f"   -> search: 确认已选中(按了{downs}次下到达), 按 A 搜索")
                    tap("a", after=1.5)
                elif downs < 9:
                    log(f"   -> search: 选中={sel!r} 非确认, 按 下 (第{downs+1}次)")
                    tap("dpad_down", after=0.6)
                    downs += 1
                else:
                    log("   -> search: 按了9次下还没选中确认, 停止(需要看清楚布局)")
                    break
            elif tag == "results":
                log("   -> 到『结果页』! 映射成功, 停止(不买)。")
                break
            elif tag in ("buyout_confirm", "bid_confirm"):
                log(f"   -> 意外到了 {tag}, 停止(不碰确认框)。")
                break
            else:
                log(f"   -> {tag}: 未知/非拍卖页, 停止(不乱按)。")
                break
    finally:
        try:
            pad.neutral()
        except Exception:
            pass
    log("映射结束。")


if __name__ == "__main__":
    main()
