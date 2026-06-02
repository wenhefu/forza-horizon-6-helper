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
  - **SAFETY (the key):** the cards are visually identical (no on-card current/fav badge),
    but the menu reveals favorite state — `detect_vehicle_action_menu().favorited`:
    **从收藏中移除 ⇒ favorited ⇒ the farm 22B the nav relies on ⇒ NEVER sell**; 添加至收藏 ⇒
    not favorited ⇒ sellable. Confirmed live: a junk 22B shows 添加至收藏. Tested.
- [ ] **Remaining before auto-removal (DESTRUCTIVE — do user-watched):**
  - **Menu-focus read:** need to know which 选择操作 option is highlighted so we land on
    从车库移除车辆 (5th) without misfiring (a misnav could hit 举报并移除涂装). The menu has a
    lime focus box like the filter — reuse `find_lime_focus_boxes` on the menu region. THIS
    is the last missing recognition piece.
  - **Confirm dialog flow** after 从车库移除车辆 (capture the 确定/取消 popup).
  - Loop: for each dup card → A → if `favorited` (从收藏中移除) **B (skip)**; else nav to
    从车库移除车辆 → A → confirm. Keep ≥1; cap per run; restore 重复项 OFF at the end.
  - **Validate with a single removal first** (1 confirmed-non-favorited junk 22B of the ~50),
    user watching, verify the farm 22B is untouched, before any bulk run.

**Phase C — Auction snipe (priority 2, largest; new runner + GUI).**
- [ ] New screen ids + recognition: `auction_house`, `auction_search`, `auction_results`
  (parse each listing's buy-now price + owned flag).
- [ ] Runner: set search filters (model + max buy-now) → 确认 → loop-refresh results →
  the instant a listing ≤ target price appears, 选择 → Y 拍卖选项 → 买断 → confirm.
- [ ] GUI: target model + max price + a Start-snipe button.

Recommended order: A → B → C (ascending size/risk; A also fixes a real buy waste today).
