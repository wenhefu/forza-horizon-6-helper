# Super-Assistant — UI Map + Build Plan

Goal (user, 2026-06-02): a program that truly understands every FH6 UI and does
more than buy+mastery. Concretely:
1. **Skill-point accounting** — know available points + per-node cost, so it never
   buys an extra car only to discover (via the 技术点数不足 popup) there were no points.
2. **Auction sniping** — search the auction house and grab a target car the instant
   it appears (buy-now).
3. **Sell duplicate cars** — auction or remove duplicates from the garage.

All screens below were captured live (1920×1080, zh-Hans) and saved under `samples/`.

## Screen map (recognizer id → reality)

### Vehicles tab — `pause_vehicle_entry` (already recognized)
Pause menu → RB to **车辆**. Tiles: 更换车辆 (已拥有 N 辆车) · 购买新车与二手车 ·
**车辆熟练度** · 秘藏座驾 · 车房宝物 · 礼物掉落箱 · 汽车喇叭 · 调校车辆.
- **Shows available skill points: `"18技术点数可用"`** on the 车辆熟练度 tile. ← read here.
- Nav: from 更换车辆 (default focus), **dpad_down → 车辆熟练度 → A** opens the tree.

### Mastery tree — `vehicle_mastery` (already recognized)
Grid of perk nodes (each with a point cost), car render on the right.
- Footer: **`"可用点数 18"`** (available points). Buy code spends a FIXED sequence
  here until the `skill_points_exhausted` (技术点数不足) popup — it never reads the count.
- `detect_skill_points()` (NEW, v3/buying_ui.py) reads the count from either surface.

### Auction house — currently MISLABELED `autoshow_buy_sell` (needs a new id `auction_house`)
拍卖场 → vertical list: **搜索拍卖** · **开始拍卖** · 我的竞价 · 我的拍卖 · 拍卖提醒.

### Auction search — currently `unknown` (needs new id `auction_search`)
搜寻: 车厂 · 型号 · 性能等级 · 车辆类型 · 最高竞价 · **最高买断价** · 确认 · 返回 ·
步步推进 · 清除搜索选项. Set filters → 确认 → results.

### Auction results — currently `autoshow_buy_sell` (needs new id `auction_results`)
`拍卖详情`: left = listing list, right = detail panel, sort `①即将结束` (ending soon).
Each listing OCRs: car name + make/year + perf number + **current bid + buy-now (买断)
price** + rarity + flags (`已拥有` owned / `成交！` sold). Hints: A 选择 · B 返回 ·
**Y 拍卖选项** (bid/buy-now) · RT 拍卖提醒.

### Per-car action menu — currently underlying grid mislabeled `eventlab_my_cars` (needs `vehicle_action_menu`)
On a car in My Vehicles, **A** opens a centered popup `选择操作`:
**拍卖车辆** · 上车 · 添加至收藏 · 查看车辆 · 查看历史记录 · **从车库移除车辆** · (A 选择 / B 取消).

### Create-auction (set price) — currently `unknown` (needs `auction_create`)
拍卖车辆 → "正在准备车辆…" load → `创建拍卖`: **起拍价** (e.g. 13,000) · **买断价**
(150,000) · **拍卖时间** (1小时) · **确认** · 返回.

### My Vehicles grid (`更换车辆` → A) — `eventlab_my_cars`
Organized by **manufacturer tabs** (LB/RB; first tab 当前车辆 = recent). Per-car cards:
**rarity** (传奇/全新/史诗/普通/稀有) + perf number, flags `当前车辆` / `已拥有`. Focused card
name = `selected_item`; left panel shows its brand (e.g. SUBARU) + stats.

### ★ Native duplicate filter (`eventlab_filter`, already recognized)
On the grid, **Y (切换筛选)** opens 筛选 with rows: 收藏 · 可用的车身套件和预设配置 ·
**重复项 (DUPLICATES)** · 性能等级 (S1/S2) · 车辆类型. Focus a row, **A = 切换 (toggle)**,
B back. Toggling **重复项** ON re-renders the grid to show ONLY duplicated models (brand
tabs shrink to just brands you own >1 of) — i.e. **the game does duplicate-detection for
us**. `detect_eventlab_filter_state` reads the focus; 重复项 is the 3rd row (its
`focused_row` parses as '' but `text`='重复项', y≈0.33). This is the key enabler for Phase B
(no full-garage scan needed).

## Build plan (phased — each its own focused effort + tests + live validation)

**Phase A — Skill-point accounting (priority 1) — DONE + live-verified.**
- [x] `detect_skill_points(ocr_text)` + 7 tests.
- [x] Buy loop (`buy_car_runner.py`, STATE_VEHICLE_TAB return_to_buy_tab): reads the
  count from `detection.ocr_text` ('X技术点数可用') after each car's mastery; if 0, stops
  instead of buying a doomed next car. Additive + guarded (None → old path; 技术点数不足
  popup still the safety net). Live-verified: on the real 车辆 tab the detector OCR holds
  '18技术点数可用' and detect_skill_points returns 18.
- [ ] (Future refinement) read per-node cost to stop at "< cheapest node" rather than 0.

**Phase B — Sell duplicates (priority 3, medium; reuses My Vehicles + the action menu).**
- [x] `detect_vehicle_action_menu(ocr_text)` — recognize the 选择操作 popup (拍卖车辆 /
  从车库移除车辆 / 添加至收藏 / 上车) + 7-case detector test.
- [x] `v4/sell_planner.py`: `plan_duplicate_sales(cards, keep_per_model=1)` +
  `summarize_plan` — the vetted decision logic with HARD safety baked in: never sell
  当前车辆 or 收藏; keep >= keep_per_model copies per model; only surplus non-protected
  copies are ever proposed. 10 tests (incl. the never-sell invariants).
- [x] **Discovery:** the native **重复项 (Duplicates) filter** (above) — enable it and the
  grid shows ONLY duplicates, so no 648-car scan. Live-confirmed toggling on/off.
- [x] **Read-only DRY-RUN scanner BUILT + live-validated** (`v4/sell_runner.py`
  `SellDuplicatesRunner` + `sell_launcher.py`): enables 重复项, sweeps with DpadRight
  reading focused names, reports the duplicated models + counts, then restores the filter.
  Live result: the garage holds a big stack of duplicate **22B** (swept to the 50-card cap —
  the buy-mastery accumulation) = the main sell target. Read-only; sells nothing. 11 tests
  (incl. `distinct_models`). **Selling stays the gated next step** (destructive):
- [x] **Sell mechanism + safety fully mapped (live).**
  - On a dup card, **A → 选择操作** (recognizer calls it `modal_warning`). The My-Vehicles
    menu is REMOVE-only: 上车 / 添加至收藏 / 查看车辆 / 查看历史记录 / **从车库移除车辆** /
    举报并移除涂装. (拍卖车辆/auction is only on the 拍卖场→开始拍卖 path.) So fast dup
    clearing = **从车库移除车辆** (sell-for-credits, instant); auctioning is the slower path.
  - **Confirm dialog (user-confirmed):** 从车库移除车辆 → "确定要移除所选车辆吗?" with
    **不 (default, No)** / 嗯 (Yes). To confirm: DpadDown → 嗯 → A. The 不 default = a misnav
    cancels safely.
  - **Card badges (user-confirmed):** green steering-wheel = currently DRIVING (current car);
    black solid heart = FAVORITED. The farm 22B has both + is tuned to **R 913**; junk copies
    are stock **B 600**.
  - **SAFETY — three independent protections for the farm 22B:**
    1. **Game-native (strongest):** the currently-DRIVING car's 选择操作 has **NO 从车库移除车辆**
       (and no 上车) — the game itself refuses to delete the car you are driving. So
       `has_remove`=False ⇒ skip. Keep the farm 22B as the driving car ⇒ literally un-removable.
    2. **Favorite:** favorited cars show **从收藏中移除 / 从我的收藏中移除** (match substring
       "收藏中移除") ⇒ `favorited`=True ⇒ skip. The nav relies on a favorited 22B.
    3. **Class:** farm = R 913 (tuned) vs junk = B 600 (stock) — a secondary distinguisher.
  - `detect_vehicle_action_menu()` now returns **`sellable = has_remove and not favorited`**
    (excludes BOTH the driving car and favorited cars). Tested.
- [ ] **Remaining before auto-removal (DESTRUCTIVE — do user-watched):**
  - **Menu-focus read:** know which 选择操作 option is highlighted to land on 从车库移除车辆
    without misfiring (reuse `find_lime_focus_boxes` on the menu region). Last recognition piece.
    Mitigated by safe defaults: menu default is 上车 (drive = harmless), remove-confirm default
    is 不 (No).
  - Loop: for each dup card → A → if NOT `sellable` (driving/favorited) **B (skip)** → else
    nav to 从车库移除车辆 → A → DpadDown → 嗯 → A. Keep ≥1; cap per run; restore 重复项 OFF.
  - **Validate with one removal first**, user watching, verify the farm 22B untouched.

**Phase B — Sell duplicates — DONE + live-validated + GUI-integrated.**
- Works end-to-end: `v4/sell_runner.py SellDuplicatesRunner.run_sell(max_sell, target_name)`
  + `sell_launcher.py` + a GUI 「开始清理」button (gui_v4). Auto-navigates to My Vehicles,
  enables 重复项, removes junk copies of the target model, restores the filter.
- 3-layer safety (all live-proven): game won't remove the DRIVING car (no 从车库移除 option);
  favorited cars skipped (从我的收藏中移除); per-deletion 确定要移除 confirm-dialog verified
  before 嗯. **Live result: 200+ junk 22Bs cleared across runs, 0 aborts, farm 22B untouched.**
- **Credits finding:** 从车库移除车辆 is a DECLUTTER, NOT a credit-sale (CR unchanged after
  200 removals). In FH the only credit-recovery for a car is the auction (player-to-player,
  impractical for hundreds). So clearing junk = freeing garage space, not earning credits.
- Speed: ~15s/car reliable. A downscale-OCR speedup was reverted (960px mis-read the menu
  rows on the destructive flow). Bigger speedup = region-OCR / template-matching of the menu
  (careful, deferred — reliability first on a delete-path). Auto-nav handles pause_story /
  pause_vehicle_entry / grid; `pause_my_horizon` start state still needs a tweak.

**Phase C — Auction snipe (priority 2, researched; new runner + GUI).**
GitHub research (2026-06): a FH6-specific OSS sniper **FrostyIsBored/FH6-Auction-House-Sniper**
uses our exact method — screen-reading + virtual input, runs only while FH6 is focused, NO
injection — confirming our path. (Others: Scruffydrew FH5 sniper, YiwenLu FH5 OpenCV buyout.)
- **In-game snipe flow (to replicate via vgamepad + screen-read):** 拍卖场 → 搜索拍卖 → set
  车厂/型号/性能/最高买断价 → 确认 → watch 拍卖详情 → when a match ≤ max-buyout appears:
  **Y (拍卖选项) → ↓ 买断(Buyout) → 确认** → collect → loop (re-search).
- **Anti-ban (from research):** Playground flags static sub-ms / robotic delays — use
  RANDOMIZED human-like tap timing (still no injection; just jittered delays). Keep the
  game foreground (already required), 1920×1080, consistent graphics.
- [x] **Screen detectors built** (`v3/buying_ui.py`, standalone like the sell ones; the
  classifier mislabels these): `detect_auction_search` / `detect_auction_results` /
  `detect_auction_house` / `detect_buyout_confirm`. 5 tests from live OCR.
- [ ] **Live-capture the buyout flow** (needs the auction open with listings): select a
  listing → **Y (拍卖选项)** → the options popup → **买断** → its confirm → 成交/失败. Refine
  `detect_buyout_confirm` outcome strings from these captures (currently guessed).
- [ ] **AuctionSnipeRunner** (DRY-RUN first; then credit-spending, user-watched): user pre-sets
  filters (型号 + 最高买断价) on 搜寻 → loop: 确认 → results → if a populated/not-sold listing →
  Y → **↓ 买断 (ONCE, never retry) + delay → confirm** → 成交? collect → loop. Randomized timing.
- [ ] GUI: target model + max buyout + Start-snipe button. (Optional: read buy-now PRICE via
  OCR to enforce "≤ max" beyond the game filter — our edge over pure template match.)

Order done: A (skill points) ✓ → B (sell duplicates) ✓ → C (auction) researched, next to build.

## Learnings from the FH6 OSS sniper (FrostyIsBored/FH6-Auction-House-Sniper)

Studied the source (cloned to D:/fh6-sniper-src; public GitHub, **no LICENSE file** -> we
learn the APPROACH/ideas, never copy code). Stack: opencv (template match) + bettercam
(dxcam fork) + mss fallback + pynput keyboard + win11toast.

**How it reads the screen:** TEMPLATE MATCHING, not a trained model and not OCR. It keeps
`templates/*.png` (search, auction_details, buy_out, buyout_success, ...) and runs
`cv2.matchTemplate` (TM_CCOEFF_NORMED, threshold 0.80), region-cropped per template, plus
HSV colour masks (lime focus banner, yellow SOLD stamp, "pure-white" populated-card pixels).
Contrast: we use YOLO ONNX + RapidOCR + rules (heavier, but reads real text/prices/skill-points
and tolerates scale/language; template-match is fast but brittle -> they require 1920x1080,
low graphics, English, and a moving-background flag).

**Techniques worth adopting (ours):**
1. **Mixed-resolution matching** — downscale most regions for speed, keep a few fine-text
   crops at FULL res (their `_FULL_RES_TEMPLATES`). This is exactly the fix for our reverted
   sell speedup: region-crop + downscale generally, full-res only for the menu text. SAFE speedup.
2. **`_press_until(key, from_screen, targets, settle, retry)`** — press, wait `settle` for the
   screen to leave `from_screen`, retry if stuck. More robust + faster than our read-every-step.
3. **Randomised timing** — jittered key hold (20-45ms) + gap (20-55ms) + poll (40-90ms). Anti-ban
   + human-like. Add jitter to our Gamepad taps.
4. **`SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)`** on the overlay so the bot never
   captures its own HUD — this is the fix for our V5 dxcam self-occlusion (GUI window in frame).
5. **Frame normalisation** — strip black bars + crop the 16:9 box in code, so ultrawide/letterbox
   works without resizing the window (complements our window_util.resize_to_16_9).
6. **HDR lime fallback** (wider HSV window) — the lime banner hue-shifts under HDR.
7. **Global panic hotkey (F9)** — emergency stop.
8. **`targets`/scoped matching** — only score templates for the expected screens (+ last-known).

**For Phase C (auction snipe) — their proven flow + safety to replicate (via our vgamepad+OCR):**
search-config -> navigate-to-Confirm (lime-highlight) -> Enter -> wait results -> wait cards
RENDERED (banner shows before cards) -> first populated+not-sold slot -> Y -> **Down ONCE (never
retry) + buyout_select_delay + Enter** (a dropped Down leaves Place-Bid highlighted, so a retried
Enter would BID credits — critical safety) -> confirm Yes (handle progress/success/failed) ->
collect -> loop. Recovery is ESC-only (never confirms). OUR EDGE: OCR can read the buy-now PRICE
and car NAME, so we can enforce "buyout <= max price" and exact-model match, which pure template
match can't.
