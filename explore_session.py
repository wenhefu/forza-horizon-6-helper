"""Persistent exploration session: keeps ONE vgamepad connected for the whole session, so Forza
does NOT auto-pause-on-disconnect between steps. Reads commands from explore_cmd.txt and, after
each, saves a screenshot + appends recognition to explore_log.txt.

explore_cmd.txt: a single line "SEQ:cmd" where SEQ is an increasing integer and cmd is either
  - comma-separated buttons: a b x y lb rb start back dpad_up dpad_down dpad_left dpad_right wait
  - "look"  (capture only, no press)
  - "quit"  (neutral + exit)
Each NEW SEQ (> last processed) is executed once. Screenshot -> samples/sess_<SEQ>.png.
"""
import os
import time

import cv2
import numpy as np

import focus
from gamepad import Gamepad
from v4.recognizer import V4Recognizer

os.makedirs("samples", exist_ok=True)
CMD = "explore_cmd.txt"
LOG = "explore_log.txt"

focus.activate_window("Forza")
time.sleep(0.6)
rec = V4Recognizer(title="Forza")
pad = Gamepad()
time.sleep(0.6)


def log(line):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        print(line, flush=True)
    except Exception:
        pass


def cap(seq):
    snap = rec.capture(full_ocr=True, region_ocr=True)
    u = snap.v3
    tries = 0
    while getattr(u, "screen", "") == "controller_disconnected" and tries < 3:
        pad.tap("a", hold=0.12)
        time.sleep(1.0)
        snap = rec.capture(full_ocr=True, region_ocr=True)
        u = snap.v3
        tries += 1
    fr = snap.frame
    arr = np.frombuffer(bytes(fr.bgra), dtype=np.uint8).reshape(fr.height, fr.width, 4)
    cv2.imwrite(f"samples/sess_{seq}.png", arr[:, :, :3])
    sel = getattr(u, "selected_item", "")
    tab = getattr(u, "active_tab", "")
    texts = " | ".join(str(getattr(it, "text", "")) for it in snap.ocr_items[:30])
    log(f"[{seq}] screen={u.screen} selected={sel!r} tab={tab!r} png=samples/sess_{seq}.png")
    log(f"     OCR: {texts}")


log("=== session start (pad stays connected) ===")
last = 0
while True:
    try:
        with open(CMD, encoding="utf-8") as f:
            line = f.read().strip()
    except Exception:
        time.sleep(0.3)
        continue
    if not line or ":" not in line:
        time.sleep(0.3)
        continue
    seq_s, _, cmds = line.partition(":")
    try:
        seq = int(seq_s)
    except ValueError:
        time.sleep(0.3)
        continue
    if seq <= last:
        time.sleep(0.3)
        continue
    last = seq
    cmds = cmds.strip()
    if cmds == "quit":
        log("=== quit ===")
        break
    try:
        focus.activate_window("Forza")   # keep Forza foreground (3D/gameplay screens need it)
        time.sleep(0.25)
    except Exception:
        pass
    if cmds and cmds != "look":
        for b in cmds.split(","):
            b = b.strip()
            if b == "wait":
                time.sleep(1.6)
            elif b:
                pad.tap(b, hold=0.12)
                time.sleep(1.4)
    time.sleep(0.6)
    cap(seq)

pad.neutral()
log("session ended")
