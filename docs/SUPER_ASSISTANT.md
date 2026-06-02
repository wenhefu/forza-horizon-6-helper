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

### My Vehicles grid (sell/auction context) — shared layout with `eventlab_my_cars`
Brand tabs (LB/RB), per-car cards with **rarity** (传奇/全新/史诗/普通/稀有) + perf number,
flags `当前车辆` / `已拥有`. Left panel: selected car stats + a suggested price.
→ duplicate detection = same car name appearing on >1 card.

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
- [ ] New screen ids + recognition: `vehicle_action_menu`, `auction_create`.
- [ ] Scan My Vehicles grid → group by car name → for each duplicate beyond N kept,
  open 选择操作 → 拍卖车辆 (创建拍卖, accept suggested price, 确认) or 从车库移除车辆.
- [ ] Safety: never sell 当前车辆 / favorites / the farm 22B; dry-run + confirm count.

**Phase C — Auction snipe (priority 2, largest; new runner + GUI).**
- [ ] New screen ids + recognition: `auction_house`, `auction_search`, `auction_results`
  (parse each listing's buy-now price + owned flag).
- [ ] Runner: set search filters (model + max buy-now) → 确认 → loop-refresh results →
  the instant a listing ≤ target price appears, 选择 → Y 拍卖选项 → 买断 → confirm.
- [ ] GUI: target model + max price + a Start-snipe button.

Recommended order: A → B → C (ascending size/risk; A also fixes a real buy waste today).
