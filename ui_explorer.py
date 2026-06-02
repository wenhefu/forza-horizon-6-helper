"""UI explorer: capture the current screen + step through a button sequence.

Usage:  python _explore.py <prefix> [btn1 btn2 ...]
Captures samples/<prefix>_0 (current), then presses each button and captures after.
Auto-dismisses the controller-disconnected modal at the start of each run.
Buttons: a b x y lb rb start back dpad_up dpad_down dpad_left dpad_right
"""
import os
import sys
import time

import cv2
import numpy as np

import focus
from gamepad import Gamepad
from v4.recognizer import V4Recognizer

os.makedirs("samples", exist_ok=True)
prefix = sys.argv[1] if len(sys.argv) > 1 else "ui"
buttons = sys.argv[2:]

focus.activate_window("Forza")
time.sleep(0.6)
rec = V4Recognizer(title="Forza")
pad = Gamepad()
time.sleep(0.6)


def cap(label):
    snap = rec.capture(full_ocr=True, region_ocr=True)
    u = snap.v3
    tries = 0
    while u.screen == "controller_disconnected" and tries < 3:
        pad.tap("a", hold=0.12)
        time.sleep(1.0)
        snap = rec.capture(full_ocr=True, region_ocr=True)
        u = snap.v3
        tries += 1
    fr = snap.frame
    arr = np.frombuffer(bytes(fr.bgra), dtype=np.uint8).reshape(fr.height, fr.width, 4)
    cv2.imwrite(f"samples/{label}.png", arr[:, :, :3])
    texts = " | ".join(str(getattr(it, "text", "")) for it in snap.ocr_items[:34])
    print(f"[{label}] screen={u.screen} | selected={getattr(u,'selected_item','')!r} | tab={getattr(u,'active_tab','')!r}")
    fs = getattr(u, "filter_state", {}) or {}
    if fs:
        print(f"   filter_state={fs}")
    print(f"   OCR: {texts}")
    return u


cap(f"{prefix}_0")
for i, b in enumerate(buttons, 1):
    if b == "wait":
        time.sleep(1.6)  # no press: just let the screen finish loading
    else:
        pad.tap(b, hold=0.12)
    time.sleep(1.5)
    cap(f"{prefix}_{i}_{b}")
pad.neutral()
print("done")
