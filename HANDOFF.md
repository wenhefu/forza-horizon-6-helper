# Handoff - Forza Horizon 6 Helper

## 2026-06-01 hotfix 27 - debounce handoff/arrival + free-roam guard + 1080p default

Multi-round live testing surfaced two more misread-driven bugs (both confirmed from `dist\reports\v4_mode3_latest.json`, the exe writes there since its CWD is dist):

1. **Later rounds went to farm with skill points unspent.** The buy phase was working (the run bought 5 cars correctly), but a SINGLE monitor frame mis-read a car grid as `eventlab_my_cars` (step 53 of 54) -> `_buy_phase_can_handoff_to_v4` fired -> buy aborted before the 技术点数不足 modal. Worse in rounds 2/3 because the post-farm point pool is large, the buy phase runs long, and more monitor frames = higher chance of one misread. Fix: **debounce the buy->farm handoff -- require 2 consecutive monitor checks** on an EventLab/race page before aborting (`handoff_streak` in `_run_buy_phase`).
2. **1600x900: after buying, the car idled in free roam holding throttle.** At smaller frames V3 mis-reads the festival start line as `race_hud` and V1 smart mis-reads it as RACING, so navigation falsely "arrived" and handed an idle car to the farm. Fixes: **debounce nav arrival -- require 2 consecutive arrival frames** (`arrived_streak` in `_navigate_to_eventlab_prestart`); the farm smart hint now **never treats `free_roam_hud` as a race** (`v4/farm_runner.py`); and the resize default is now **1920x1080** (larger frame = reliable recognition; 1600x900 mis-read, 1080p ran clean).

These are decision-layer fixes (tolerate the occasional misread) -- no model retraining / sample collection needed. `test_buy_phase_monitor_hands_off_after_buy_runner_started` updated to the 2-frame debounce. 133 passed, 22 skipped.

## 2026-05-30 hotfix 26 - V4 mode-three end-to-end fixes + 16:9 window normalize

Co-op debugging of a full buy+farm loop surfaced four real bugs (all fixed, each with a regression test) plus a new robustness feature. The whole mode-three round now runs end-to-end (buy 22B -> mastery -> points exhausted -> EventLab -> vision farm -> graceful exit) and loops.

1. **Buy phase never bought (the car).** `_recognize_buy_monitor` used `full_ocr=False` (hotfix 24's speed-up). Dense car grids (制造商列表/斯巴鲁车展) share the card-grid structure of `eventlab_my_cars`, so without OCR text they were mislabelled `eventlab_my_cars` -> `_buy_phase_can_handoff_to_v4` fired -> BuyCarRunner was stopped mid-purchase. Fix: the buy monitor uses **full OCR** again (it only ticks every watchdog/10s <= 8s, so the cost is negligible). `v4/mode3_runner.py`.
2. **`loop_rounds=0` stopped after one round.** A loop needs the post-farm cleanup to return to a known pause-menu start; if `刷图结束后回收尾` was unchecked, `run_loop` silently degraded to a single round. Fix: a loop now **auto-enables `exit_after_farm`** (runner + GUI auto-ticks the box + hint "0=无限循环(自动开回收尾)"). `v4/mode3_runner.py`, `v4/gui_v4.py`.
3. **Farm never auto-started after a non-restart popup.** `decide_farm_loop` only pressed A on the explicit 重新开始赛事 modal; any other `modal_warning` fell to `farm_wait_unknown` and the runner just waited forever. Fix: **any farm popup -> press A to proceed** into the race (B only while gracefully exiting); the confirm also opens the launch-throttle window. `v4/decision.py`, `v4/farm_runner.py`.
4. **Navigation false "arrived" -> car left idling in free roam.** After backing out of the buy flow (B B B) the player lands in free roam at the festival start line. V3 reads it as `unknown`; V1's fixed-fraction smart detector mis-reads the checkered start line as `RACING`; `_smart_state_confirms_eventlab` then confirmed arrival on smart=RACING+`unknown` and handed off to the farm, which sat idle. Fix: **"arrived at racing" now requires a real V3 `race_hud`** (dropped `unknown`/`loading` from the racing set), and a new `_decide` rule turns "V1 says RACING but V3 has no race_hud" into **open the pause menu (Menu) and keep navigating**. The PRESTART fallback (V3 misses the start menu, V1 sees it) is kept. `v4/mode3_runner.py`.

**New feature - normalize the game window to 16:9 (`window_util.py` + GUI button "把地平线调成 16:9").** The buy phase and the farm smart-hint still partly rely on V1's 16:9 fixed-fraction detector, which is exactly what broke on a friend's ultrawide (带鱼屏). Pure Win32 `SetWindowPos` (no inject/hook/focus-steal; `SWP_NOACTIVATE`) resizes the game's CLIENT area to a chosen 16:9 preset (1280x720 / 1600x900 / 1920x1080, default 1600x900), so the fixed-fraction detection sees the same aspect on any monitor. Verified live: Forza accepted the resize (1174x660 -> 1600x900, aspect 1.778). Requires the game in windowed/borderless mode (it reports clearly if the game is fullscreen-exclusive). Top-left is preserved so the title bar never lands off-screen (multi-monitor safe).

**GUI defaults** now match the validated run: `跑图=3`, `完整循环=0`(无限), `跳过买车=off`, `刷图结束后回收尾=on`, `自动切回前台=on`, 刷图引擎=视觉制导.

133 passed, 22 skipped. `dist\Forza6HelperV4GUI.exe` rebuilt from this tree.

## 2026-05-30 hotfix 25 - V4 GUI readability polish + tidy

User feedback: GUI fonts too small / design too plain.
- `v4/gui_v4.py`: bigger fonts (body 9->11, title 15->19, section 10->13, log mono 9->11), larger/bolder buttons, and a compact field layout -- label + entry + hint are clustered left in a packed row frame instead of a far-right hint with a big empty gap. Window stays resizable with the log box growing to fill (from hotfix 22). No behavior change; the runner wiring is untouched.
- `.gitignore`: ignore `datasets/forza_ui/_pruned/` (the quarantined junk frames from hotfix 16) so it stops showing up in `git status`.
- 127 passed. The packaged `dist\Forza6HelperV4GUI.exe` already reflects this (gui_v4.py was on disk when the hotfix-24 exe was rebuilt). If a future GUI swap to CustomTkinter is wanted (rounded/flat/dark, genuinely modern), that is a separate larger change + a new dependency + repackage.

## 2026-05-30 hotfix 24 - V4 fast-path recognition pacing

User feedback after the latest GUI report: the V4 flow felt extremely slow ("like an old person looking at a phone"). The report confirmed the bottleneck was not YOLO inference: dense buy-grid/manufacturer full-frame OCR samples reached 4-7s each, and fixed post-button settle waits added more latency.

Changed:
- `v4/mode3_runner.py`: `_recognize()` now accepts `full_ocr` / `region_ocr` flags. The V1 BuyCarRunner supervision heartbeat uses `_recognize_buy_monitor()` (`full_ocr=False`, small-region OCR still on), so it can catch route handoff/stalls without doing full-screen OCR over dense car grids every few seconds.
- `v4/mode3_runner.py`: shortened conservative fixed settle waits (`A` route transitions 1.8s -> 1.15s, normal steps 0.85s -> 0.55s) and reduced buy-monitor churn (`_child_watchdog_interval` caps at 8s instead of 5s).
- `v4/farm_runner.py`: Vision farm loop now captures with `full_ocr=False` by default and applies the existing V1 lightweight color/layout detector as a safety hint for `race_hud`, `race_result`, restart modal, prestart, controller modal, pause, and post-race pages. This keeps the farm leg snappy while avoiding the known YOLO `race_menu` vs `race_hud` confusion.
- `tests/test_v4_mode3.py`: added regressions for the fast buy-monitor flags and the farm smart-hint fallback.

Verification:
- `python -m py_compile v4\mode3_runner.py v4\farm_runner.py tests\test_v4_mode3.py`
- `python -m pytest tests\test_v4_mode3.py -q` -> 60 passed
- `python -m pytest -q` -> 127 passed, 22 skipped

No V1 stable main-flow files were edited. Next live validation should compare the next `reports\v4_mode3_latest.json` phase totals against the previous 212.7s run; expected win is fewer multi-second `monitor_buy_phase` OCR stalls and faster EventLab/farm button cadence.

## 2026-05-30 hotfix 23 - Require EventLab vehicle favorite filter before selecting 22B

Latest GUI report (`reports/v4_mode3_latest.json`, 2026-05-30 09:53:31-09:57:04) showed V4 reaching `eventlab_my_cars` with selected item `IMPREZA 22B-STI VERSION` and immediately issuing `select_22b_for_eventlab`. That skipped the intended `Y -> 收藏筛选 -> B` verification because `_eventlab_my_cars_decision()` checked `is_22b()` before `favorite_filter_done`.

Changed:
- `v4/decision.py`: `eventlab_my_cars` now opens the vehicle filter first whenever `favorite_filter_done` is false, even if OCR says the current focused car is 22B. Only after the filter is confirmed and returned does V4 allow `select_22b_for_eventlab`.
- `tests/test_v4_mode3.py`: added a regression that 22B without `favorite_filter_done` produces `open_vehicle_favorite_filter` / `Y`.

Report note:
- The same report took 212.7s and failed as `farm_phase_failed` after stopping during/just after handoff. Buy-phase semantic monitoring was the slowest part: 26 buy monitor samples accumulated 80.3s of recognition time, especially dense car-grid/manufacturer OCR samples. This is mostly V1 `BuyCarRunner` + full OCR supervision, not the V3 farm loop itself.

## 2026-05-30 hotfix 22 - V4 GUI, resilient loop recovery, standalone packaging

Builds on hotfix 21's outer loop.

V4 runner GUI (run it yourself so Forza stays foreground -- avoids the background-launch focus problem):
- `v4/gui_v4.py` + `v4_gui_launcher.py`: a V1-style tkinter GUI driving `V4Mode3Runner`. Options: 跑图时间(分钟), 完整循环轮数, 连续失败上限, 看门狗(秒), 启动倒计时, checkboxes (跳过买车/跳过刷图/刷图后收尾/自动切回前台), 刷图引擎 vision|smart. Live log, ViGEmBus driver status, 开始/停止/切回游戏/打开报告. Single-instance guard (`Local\\Forza6HelperV4`) + `multiprocessing.freeze_support()` so only one window opens (a 2nd pythonw at launch is an onnx worker, not a window).
- Run: `.venv\Scripts\pythonw.exe v4_gui_launcher.py`.

Resilient outer loop (a failed round no longer kills the whole loop):
- `mode3_runner.run_loop(..., max_consecutive_failures=3)`: on a failed round it calls `_recover_between_rounds(pad)`, which backs out to a safe menu using ONLY B / Menu (and A for the controller modal) -- it never blind-presses A on grids/cards (that is what risks a mis-buy or a Photo-Mode-style mis-trigger) -- then retries the round. It stops only after `max_consecutive_failures` consecutive failures. `start()` threads the param; the GUI exposes it as 连续失败上限. 2 new tests (retry-then-complete, stop-after-max). 122 passed.
- For continuous 买车+加点+刷图 loops: 完整循环轮数=0, uncheck 跳过买车, finite 跑图时间, keep 刷图后收尾. For the most robust unattended farming: check 跳过买车 + 跑图时间=0 (one leg, vision farm restarts races forever).

Standalone packaging (runs on other PCs without Python):
- `Forza6HelperV4GUI.spec` + `build_v4_gui.bat` -> `dist\Forza6HelperV4GUI.exe`. Onefile, `console=False` (windowed), bundles `v3/models` + onnxruntime + rapidocr + vgamepad, excludes torch/ultralytics. The target PC still needs the ViGEmBus driver; the GUI checks it on startup and opens the install page if missing.
- Build: `build_v4_gui.bat` (or `pyinstaller --clean --noconfirm Forza6HelperV4GUI.spec`).

No V1 stable main-flow files were edited.

## 2026-05-30 hotfix 21 - V4 full mode-three outer loop control

Clarification from user: after the 3-minute farm leg, "loop" should mean returning to buy/skill-points and then farming again, not only restarting races inside the farm runner.

Changed:
- `v4/mode3_runner.py`: added `run_loop(..., loop_rounds=...)` and `--loop-rounds`. `1` preserves the old one-leg behavior; positive values repeat full mode-three legs; `0` means repeat full legs until stopped or a leg fails. Only the first round uses `startup_delay`.
- `v4/gui_v4.py`: added `完整循环轮数` (`1=一轮;0=一直买车+刷图`) and passes it into the runner. The GUI now warns if outer looping is enabled while `跳过买车` is still checked, or while `跑图时间=0` makes a single farm leg infinite.
- `tests/test_v4_mode3.py`: added regression tests for loop-round parsing and multi-round `run_loop`.
- `README_V4.md`: documented `--loop-rounds`.

Operational semantics:
- `跑图时间=3` + `完整循环轮数=1`: buy/nav/farm for about 3 minutes, then finish.
- `跑图时间=3` + `完整循环轮数=0` + `跳过买车=否`: repeat buy/skill -> EventLab -> farm 3 minutes -> cleanup forever, until stopped/failure.
- `跑图时间=0`: the current farm leg is infinite, so the outer loop will not advance to the next buy cycle unless the farm runner exits.

## 2026-05-30 hotfix 20 - V4 farm duration zero is truly continuous

User expected the V4 GUI's `跑图时间(分钟)=0` label (`0=一直跑`) to mean a continuous farm. The GUI label was ahead of the runner behavior: GUI passed `None`, and `V4Mode3Runner._farm_seconds(None)` converted it to the config default 90-minute leg.

Changed:
- `v4/gui_v4.py`: when farm minutes is `0`, pass `0.0` explicitly instead of `None`.
- `v4/mode3_runner.py`: `_farm_seconds(0 or negative)` now returns `None`, and `_run_farm_phase(None, ...)` starts the selected farm runner with `total_seconds=None` and does not trigger the target-duration graceful-exit/watchdog path.
- `tests/test_v4_mode3.py`: added regressions for unlimited farm phase and for `0` vs omitted farm duration.
- `README_V4.md`: documented `--farm-seconds 0`.

Semantics:
- `farm_minutes=3` means repeat races for about 3 minutes, then finish the current race, exit results, and let V4 complete the current mode-three leg.
- `farm_minutes=0` means keep the farm runner going continuously until the user stops it or the farm runner's own stall watchdog exits.
- This is still not the full V1-style outer buy/farm loop. V4 GUI currently runs one mode-three leg. Full outer looping should wait until the vision buy runner replaces the V1 buy phase.

## 2026-05-30 hotfix 19 - Vision buy-phase decision foundation + full mode-three x2 live findings

Full mode-three x2 live run (`run_mode3_x2.py`, farm 3min/round, watchdog 180s):
- Round 1: `buy_phase_failed`. The game started on the post-race `race_result` page (not free roam) AND was not foreground (the foreground window was '游戏用户界面', all SetForegroundWindow activations failed), so the V1 BuyCarRunner sat on the results page (state=unknown) and the buy watchdog stopped it after 3 min -- the requested 3-minute stall guard worked.
- Round 2: `completed`, farm_laps=7, race_hud_frames=44. The vision farm loop ran the full clean cycle and the `_exit_after_farm` race_result->A fix worked ("已回到可安全交还的菜单"). Genuine farming re-confirmed.
- Neither round actually bought a car (round 1 stuck, round 2 skipped buy because the game was already in the race area). The vision FARM is solid; the V1 BUY phase is the weak link (brittle, needs a free-roam start + foreground).

Buy-flow recognition assessment (real samples): the V3 hybrid reliably IDs the buy screens despite low YOLO sample counts (V2 rules + OCR carry them): `vehicle_buy_grid` 8/8 (reads 'IMPREZA 22B-STI VERSION'), `manufacturer_grid` 7/8, `purchase_confirm` 4/4, `vehicle_mastery` 8/8, `skill_points_exhausted` 1/1, `car_preview` 6/6, `color_select` 4/4, `pause_vehicle_entry` 8/8. So a vision buy is feasible, and the hybrid's direct 22B-name read enables a "scan until 22B selected" approach (cleaner than V1's OCR grid coordinates).

New: `v4/decision.py` `decide_buy_loop(v3, BuyContext)` -- vision buy decision foundation mirroring BuyCarRunner (pause->车辆->购买新车与二手车->车展->制造商/斯巴鲁->22B->设计/颜色/预览->购买确认->加点->技术点数用完), with V1's safety gates: never press A on purchase-confirm/preview/color/design unless `context.purchase_armed` (22B positively selected), terminal on `skill_points_exhausted`. Added `BuyContext`, `looks_like_subaru`. 5 new tests incl. the never-buy-unconfirmed gate. 116 tests pass.

NOT done (next, and the harder half): the vision buy RUNNER. The grid scan (scan vehicle/manufacturer grids until 22B/Subaru is selected, with rollback) and the skill-mastery spend (V1 uses a fixed 11-step "wheelspin" sequence: A->right->A->up->A->up->A->up->A->left->A, then watch for the exhausted modal) are stateful multi-step actions that must live in the runner, plus wiring `--buy-mode vision` into mode3_runner. This needs supervised live iteration (it spends CR and has many steps) -- best nailed on 16:9 first, then ultrawide (which still needs the friend's real samples). The V1 buy still works on 16:9 as the fallback.

## 2026-05-30 hotfix 18 - Vision farm loop: live-smoke fixes (start-on-empty-focus, controller keyboard recovery)

Continuation of hotfix 17. Ran four live smokes of the vision farm loop (`--skip-buy --farm-mode vision`); each surfaced and fixed one edge case. Only `v4/farm_runner.py` changed here (plus this doc).

Fixes added on top of 17:
- `race_menu` detected but the start-focus text was not OCR'd (selected empty): the farm runner now presses `A` to start when it is NOT mid-race (the EventLab start menu's default focus is 开始赛事). It still never presses DpadUp; during launch/race the same ambiguous frame is handled as throttle, not A.
- Controller-disconnected recovery: try the virtual pad's `A` first (works once the pad is warm); if it persists, the game has fallen back to keyboard input (the modal shows `Enter 确定`), so the runner does a real title-bar click to focus + presses keyboard `Enter`. Focus loss (e.g. other window activity / a sampler process exiting) drops the virtual pad; this recovers without stalling. Added `_click_to_focus` / `_press_enter` to `VisionFarmRunner`.

Live-smoke results:
- Navigation worked end-to-end every time (creative hub -> EventLab -> 我的收藏 -> SP Farm -> single player -> 22B).
- Smoke 2: farm loop started a race and completed 3 laps (race_hud seen, results->X restart, restart modal->A). Then a DpadUp "calibrate" press on a misread start-line frame opened Photo Mode -> fixed in 17 (DpadUp removed + launch window).
- Smoke 4 (after fixes): started via A, then 25 `results->X` cycles in 60s + graceful exit at the time limit, NO Photo Mode, clean completion.

RESOLVED (smoke 5, instrumented): the self-verify summary reported `起赛/重开 3 次, 识别到驾驶画面 24 帧` -- 24 confirmed `race_hud` (driving) frames across 3 laps, i.e. the loop genuinely races (not spinning on a misread results page). The full cycle ran clean: race_hud -> results -> X restart -> confirm modal -> A -> start (incl. the empty-focus pause_story -> A start path) -> race_hud. No Photo Mode.

Remaining bug found in smoke 5 and fixed: `_exit_after_farm` got stuck pressing `B` on the post-race `race_result` standings page (B does not leave it) -> `exit_after_farm_failed`. Fixed: `_exit_after_farm` now presses `A` on `race_result` to advance (results -> next -> free roam) before falling back to B. So the farm itself worked end-to-end; only the between-cycles cleanup needed this.

Verification: `python -m pytest -q` -> 111 passed, 22 skipped. No V1 stable files changed.

## 2026-05-30 hotfix 17 - Vision-guided farm loop (VisionFarmRunner) + Photo Mode safety fix

Goal: make V4 mode-three robust across resolutions by moving the farm phase off V1's fixed-fraction `SmartRunner` onto the aspect-robust V3 hybrid (this is the part the user ran for days and the part that broke on a friend's ultrawide; the simulated-ultrawide test in this session passed).

New / changed:
- `v4/decision.py`: `decide_farm_loop(v3, graceful_exit)` -- a vision farm state machine (race_menu/prestart->A start, race_hud->hold throttle, race_result->X / graceful A, restart-confirm modal->A or B, post_race_next->B, race_pause_menu/pause_*->B, controller_disconnected->A). It trusts the focused-tile text `开始(竞赛)赛事` to start a race even when the start menu mis-reads as pause_story, and it NEVER emits DpadUp.
- `v4/farm_runner.py` (new): `VisionFarmRunner`, mirrors the SmartRunner interface (start/stop/is_running/request_graceful_exit/exit_reason). Throttle persists between cycles so driving stays smooth while it re-recognizes. A "launch window" holds throttle through the post-start countdown/loading until the HUD confirms. Stall watchdog + graceful exit.
- `v4/mode3_runner.py`: `--farm-mode {vision,smart}` (default vision; smart = V1 SmartRunner fallback). Farm phase now uses the selected runner, reuses the single `V4Recognizer` (no double ONNX load), generic `_join_runner`.
- `v3/hybrid.py`: fusion guard -- a confident V2 driving-HUD (`race_hud`/`free_roam_hud`, conf>=0.70) is no longer overridden by a YOLO menu/focus detection. This fixed `race_hud` being 100% misclassified as `race_menu` (the YOLO model over-fires race_menu).
- `tests/test_v4_mode3.py`: 11 new tests, including `test_farm_loop_never_emits_dpad_up`.

Recognition findings (the weak area is the race states):
- race_hud<->race_menu confusion: YOLO false-positive race_menu beat a confident V2 race_hud. Fixed in `_fuse_screen`.
- race_menu<->pause_story confusion: the EventLab race start menu often classifies as `pause_story`. Mitigated by trusting the `开始赛事` focus text in `decide_farm_loop` (verified 7/8 on real samples).
- At the start line / countdown the HUD text (进度/时间/KM/H) is not rendered, so V2 does not say race_hud -> those frames mis-read as race_menu. The launch window holds throttle through that window.
- DANGER fixed: D-pad Up during a race opens Photo Mode in Forza. The first vision-farm smoke pressed DpadUp ("calibrate cursor") on misread start-line frames and opened Photo Mode. DpadUp is now removed from the farm loop entirely.

Live smoke (`--skip-buy --farm-mode vision`):
- Navigation worked end-to-end autonomously: creative hub -> EventLab -> 我的收藏 -> SP Farm -> single player -> selected 22B.
- Farm loop started races, drove, completed 3 laps (results->X restart, restart modal->A). Core loop is functional.
- Photo Mode mis-trigger found and fixed (DpadUp removal + launch window). Re-smoke of the fixed loop is still pending.

Verification:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 111 passed, 22 skipped
.\.venv\Scripts\python.exe -m py_compile v3\hybrid.py v4\decision.py v4\farm_runner.py v4\mode3_runner.py
# decide_farm_loop validated on real race samples; race_hud confusion fixed (20/20 correct after fusion guard)
```

Run:
```powershell
.\.venv\Scripts\python.exe -m v4.mode3_runner --skip-buy --farm-seconds 75 --farm-mode vision --watchdog-seconds 60 --auto-focus
# Needs Forza foreground (background SetForegroundWindow is blocked) and the game at/near the EventLab 开始赛事 menu.
```

Residual / next:
- Re-smoke the fixed farm loop end-to-end (confirm no Photo Mode, car launches, multiple clean laps).
- Deeper recognizer fix: classify start-line/countdown as race_hud (reduce reliance on the launch-window + start-focus-text workarounds); retrain YOLO to stop race_menu over-firing and strengthen race states.
- Buy phase still uses V1 `BuyCarRunner` (fixed-fraction, brittle on ultrawide) -- migrate to vision next for full robustness.
- Ultrawide still needs the friend's real 21:9 samples for true validation.
- No V1 stable main-flow files were edited.

## 2026-05-29 hotfix 16 - Human-in-the-loop co-op capture + race_pause_menu recovery

User asked to evaluate the sample-collection tooling and help close the audit deficits by walking the mode-three flow. We ran a co-op collection pass: the user drove with a real controller, a new tool captured on screen-change and sent no input.

New tool:
- `v3/coop_capture.py`: human-in-the-loop capture-on-change sampler. Sends NO input. A cheap downscaled-grayscale diff gates the expensive OCR/analysis (so the game does not stutter), `--min-interval` limits save rate, and a semantic de-dupe skips re-saving the same `(screen, selected_item)` within `--resave-cooldown` (kills the 3D-car-rotating-behind-a-static-menu spam). Uses the V3 `HybridVisionRecognizer` for labels (falls back to V2 if ONNX will not load). Stop via `reports/coop_capture_stop.flag` or `--max-seconds`.

Key runtime findings (vgamepad / focus), discovered while probing before any long run:
- A freshly created vgamepad's `A` does NOT dismiss the `控制器未连接` modal (cold pad). Keyboard `Enter` does, but only after a real title-bar click to focus the window. Once the pad has been alive a few seconds it works for both navigation (RB/LB/dpad verified) and modal dismissal.
- `SetForegroundWindow` from a background-launched process is blocked by Windows. A real `mouse_event` click on the title bar is required to focus Forza, or keep it foreground manually.
- `race_sampler` stalls at Creative-Hub -> EventLab landing: the recognizer labels both the creative-hub-with-eventlab-tile page AND the EventLab landing page (`游玩赛事/创建/...`) as `eventlab_home`, and `race_sampler` only presses `A` once (never `游玩赛事`), so it times out waiting for `eventlab_events/favorites`.

Data fix this pass:
- `coop_capture` v1 used the V2 analyzer (via `SampleCollector.analyze_frame`), which lacks `race_pause_menu` detection, so in-race pause frames were saved correctly but mislabeled `pause_story`. A targeted V3 relabel (V3 hybrid has the locked-tile `race_pause_menu` fallback from hotfix 13) recovered 11 frames `pause_story -> race_pause_menu` (incl. 3 from an earlier walk). `coop_capture` now uses the V3 hybrid so future walks label these correctly without relabeling. `relabel_raw_samples.py` is V2-only and would overwrite this; do not run it globally over the V3-relabeled frames.

Known remaining recognizer gap:
- `pause_creative_hub` stays at 10 because the creative-hub page is labeled `eventlab_home` (same overloaded-label root cause; neither V2 nor V3 distinguishes 创意中心 from the EventLab landing page). The samples exist hidden in the 80 `eventlab_home` rows. Needs a recognizer fix that separates 创意中心 (tiles: 地产/车库布局/涂装设计) from EventLab landing (游玩赛事/创建/参加挑战/预制件).

Collection results (raw 995 -> 1226, net after pruning 47 junk):
- `vehicle_buy_grid` 2->17, `race_menu` screen 1->15 / YOLO 19->59, `eventlab_filter` 0->9, `race_pause_menu` 0->11, `eventlab_my_cars` 14->30, `my_cars_card_focus` 22->53, `autoshow_buy_sell` 4->28, `race_hud` 19->44 (ok), `skill_points_exhausted` 0->1, `color_select` 1->4, `car_preview` 3->6, `purchase_confirm` 2->4.
- Cleanup: moved 47 junk frames (33 `unknown` transition + 14 `race_sampler` `eventlab_home` timeout dupes) to `datasets/forza_ui/_pruned/` (reversible).

Still critically short (next pass):
- `race_result` 7/80, `post_race_next` 5/80: the user paused a lot but did not finish a race this walk; needs actually-completed races (linger on result + next-stop pages).
- `vehicle_buy_grid` 17/100, `design_card_focus` 1/50 (never entered the design/livery grid), `eventlab_filter` 9/60, `race_pause_menu` 11/60.

Commands:
```powershell
.\.venv\Scripts\python.exe -m v3.coop_capture --title Forza --max-seconds 1500 --resave-cooldown 4
# stop early: create reports\coop_capture_stop.flag
.\.venv\Scripts\python.exe -m v3.dataset --no-augment
.\.venv\Scripts\python.exe -m v3.dataset_audit --raw-root datasets\forza_ui\raw --dataset-root datasets\forza_ui\yolo --output-dir reports
```

Safety / scope: the tool sends no input; collection was co-op with the user's real controller. No V1 stable files changed. New file: `v3/coop_capture.py`. Modified: ~11 raw `metadata.json` (screen relabel only), regenerated `datasets/forza_ui/yolo`. Not yet committed. Next: retrain YOLO on the improved set (augmented `v3.dataset` first), fix the `eventlab_home`/`pause_creative_hub` overloaded label, and one short walk that finishes races for `race_result`/`post_race_next`.

## 2026-05-29 hotfix 15 - Dataset audit and targeted collection plan

User asked how to solve the gap where the dataset is already over 1GB but still has insufficient sample balance. The answer is now implemented as tooling, not just advice.

Changes:
- `v3/dataset_audit.py`: new audit CLI that reads YOLO labels/images, `summary.json`, and raw `metadata.json`, then reports class deficits, screen-semantic deficits, empty labels, missing images, invalid label rows, repeated label geometries, window-size distribution, and a prioritized collection plan.
- `v3/gui_v3.py`: added a "审计样本缺口" button that writes `reports/dataset_audit_latest.md/json` and displays the plan in the GUI.
- `v3/dataset.py`: `data.yaml` generation no longer forces an absolute local path when the dataset root is passed as a relative path.
- `tests/test_v3_dataset_audit.py`: regression coverage for class deficit calculation, screen deficit calculation, markdown output, and relative `data.yaml` paths.
- `README_VISION.md`: added the dataset audit command and current top deficits.

Latest local audit command:
```powershell
python -m v3.dataset_audit --raw-root datasets\forza_ui\raw --dataset-root datasets\forza_ui\yolo --output-dir reports
```

Latest audit summary:
- raw metadata: 995
- YOLO images: 993
- YOLO labels: 993
- empty label files: 218
- missing label images: 0
- invalid label lines: 0
- possible duplicate label signatures: 647
- top deficits: `vehicle_buy_grid` 2/100, `my_cars_card_focus` 22/120, `eventlab_my_cars` 14/100, `eventlab_filter` 0/60, `race_pause_menu` 0/60, `race_result` 5/80, `post_race_next` 4/80.

Interpretation:
- The 1GB+ dataset size is mostly high-resolution PNG volume and repeated/near-repeated pages. It does not mean enough effective labeled diversity.
- Next collection should be quota-driven: buy-grid/vehicle-grid, EventLab filter, race pause locked UI, race menu, race result/post-race, color/design/purchase flow, and different real window sizes.

## 2026-05-29 hotfix 14 - Full V4 mode-three run completed

This pass finished the requested V4 validation using the current V3/V4 recognition stack and the packaged executable. V1 stable runner files were not edited.

Changes:
- `v4/decision.py`: recognizes the EventLab entry label `游玩赛事`, recognizes the `重新开始赛事` confirmation modal, and treats that modal as a verified one-shot `A` confirmation instead of an unknown modal.
- `v4/mode3_runner.py`: buy preflight can hand off directly when a restart-event modal is already visible; Smart/V3 disagreement on the prestart menu is accepted when V3 says `pause_story` and the selected item contains `开始...赛事/竞赛`.
- `v4/mode3_runner.py`: post-farm cleanup now accepts `race_menu` and `race_pause_menu` as safe handoff states, in addition to ordinary `pause_*` pages. This fixes the previous false failure where V4 had already returned to the EventLab start menu but still reported `exit_after_farm_failed`.
- `tests/test_v4_mode3.py`: added regressions for restart-event modal handoff, prestart menu confirmation, extended post-farm verification, and accepting `race_menu` as a safe handoff.

Verification:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 97 passed, 22 skipped

.\build_v4.bat
# V4 build complete: dist\Forza6HelperV4.exe

dist\Forza6HelperV4.exe --title Forza --farm-seconds 60 --watchdog-seconds 120
# reports\v4_mode3_latest.json: completed=true, stopped_reason=completed
```

Runtime evidence:
- Latest successful run: `reports\v4_run_20260529-154344.err.log` / `reports\v4_mode3_latest.json`.
- Start: normal pause/story page with controller modal recovery.
- Buy phase: entered vehicle page, moved to festival, opened autoshow, selected Subaru/22B, confirmed purchase, returned through upgrade/mastery flow, and stopped the V1 buy phase at the known `不够购买额外加成` dialog.
- V4 navigation: closed the skill-points dialog, backed out to free roam, opened pause, reached the EventLab start/race menu, and handed off to V1 `SmartRunner`.
- Farm phase: `SmartRunner` ran for the requested 60 seconds. It did not self-finish within the extra 120 second grace window, so the V4 farm watchdog stopped it, neutralized the pad, and continued cleanup. This is the intended anti-stall behavior requested for two-minute stalls.
- Cleanup: V4 recognized `free_roam_hud`, pressed `Start/Menu`, recognized `pause_story`, and completed the run. The final report contains `completed: true` and `stopped_reason: completed`; it also records the watchdog intervention as `farm_watchdog_stop after 180.1s`.
- No `Forza6HelperV4.exe` helper process remained after the run.

Current residual risk:
- `reports\v4_mode3_latest.json` still records the farm watchdog intervention as an error entry even though the overall run completed. That is useful evidence but may look scary in the GUI/report; a future polish pass can rename it to a warning when cleanup succeeds.
- The latest run spent another 86,000 CR by buying an additional 22B, as expected for a true mode-three buy phase test.

## 2026-05-29 hotfix 13 - Race pause lock-state, checkbox evidence, and buy watchdog

User pointed out that locked Creative Hub/Vehicle tiles mean the game is still inside an active race/activity pause menu. Treating that frame as normal `eventlab_home` is wrong, because it can lead to pressing `A` on locked EventLab/garage-layout cards.

Changes:
- `v3/hybrid.py`: added a visual `race_pause_menu` fallback. It detects the locked/dimmed pause-menu layout from top pause tabs, low-brightness locked tiles, and a lime focus rectangle, even when OCR is unavailable or OCR says `eventlab_home`.
- `v3/ui_tree.py`: added `race_pause_menu` as a first-class UI node. The safe path is `B` back to the current race; switching to the story tab is only for an explicit return/quit-race inspection path.
- `v4/decision.py`: `race_pause_menu` maps to `resume_from_race_pause_menu` with `B`, and verification requires `race_hud`, `race_menu`, `idle_showcase`, or another explicit game state.
- `v3/buying_ui.py` and `v3/types.py`: checkbox output now includes direct evidence from the small square and prints `未勾选（空框）` vs `已勾选（有白色对勾）`.
- `v3/gui_v3.py`: the summary line and preview overlay now show the favorite-filter checkbox state more visibly.
- `v4/mode3_runner.py`: buy phase supervision now records semantic screenshots, closes a stable `world_map` once with `B`, restarts BuyCarRunner once, and can hand off to V4 navigation if BuyCarRunner has already reached an EventLab/race-route page.
- `v4/mode3_runner.py`: buy phase preflight now skips BuyCarRunner entirely when V4 starts from `race_hud`, `race_pause_menu`, or an EventLab/race-route page, so restarting V4 mid-race cannot accidentally begin the buy-car loop.
- `v4/mode3_runner.py`: if buy preflight is covered by a controller-disconnected modal, V4 dismisses it with one normal `A`, captures again, and still refuses to start BuyCarRunner when the cleared state is already a race/prestart route.

Verification:
```powershell
python -m pytest -q
# 81 passed, 22 skipped

.\.venv\Scripts\python.exe -  # replayed reports/current_probe.png with real RapidOCR
# ocr 32 [...]
# race_pause_menu 赛事暂停 EventLab B 返回当前比赛

.\build_v4.bat
# V4 build complete: dist\Forza6HelperV4.exe
```

Runtime observation:
- A packaged short run before the final visual-precedence fix safely recovered from the locked EventLab mistake by closing `功能尚未解锁` and returning to `race_hud`, but it proved the pre-click classification was too late. The replay after the fix classifies the same locked pause frame as `race_pause_menu` before any `A`.
- Final packaged short run on 2026-05-29 11:04: `dist\Forza6HelperV4.exe --title Forza --skip-farm --auto-focus --watchdog-seconds 20` dismissed the controller modal, recognized `smart=racing`, skipped BuyCarRunner, and completed without starting farm.
- Final packaged short-farm run on 2026-05-29 11:05: `dist\Forza6HelperV4.exe --title Forza --farm-seconds 2 --watchdog-seconds 4 --auto-focus --no-exit-after-farm` dismissed the controller modal, skipped BuyCarRunner, handed to SmartRunner, and the farm watchdog stopped SmartRunner after the short target window. `reports\v4_mode3_latest.json` records the expected `farm_watchdog_stop`.
- Current rebuilt exe: `dist\Forza6HelperV4.exe`, timestamp `2026-05-29 11:02`.
- No `Forza6HelperV4.exe` helper process remains running after the latest checks.
- V1 stable main-flow files were not intentionally edited.

## 2026-05-29 hotfix 12 - Checkbox truth, locked-modal A close, and farm watchdog

User asked whether the EventLab filter `收藏` box is actually checked. The correct visual rule is:

- empty small square on the right = not checked
- square with a white check/tick stroke = checked

Changes:
- `v3/buying_ui.py`: checkbox detection now reads the small square itself and requires an interior tick-shaped signal. OCR text and the focused row are not enough to mark `收藏` as checked.
- `v4/decision.py`: known locked/unavailable modals now close with `A` because the observed modal is an OK/confirm prompt. V4 then records `locked_feature_seen`, backs out once, and refuses to re-enter the same locked EventLab entry loop.
- `v4/mode3_runner.py`: V1 `SmartRunner` farm handoff now has its own V4 watchdog. After `farm_seconds` is reached, V4 waits at most `watchdog_seconds`; if SmartRunner still has not exited, V4 calls `stop()`, joins briefly, records `farm_watchdog_stop`, neutralizes the pad, and exits instead of hanging in the background.
- `v4/mode3_runner.py`: V1 `STATE_RACING` is accepted as a terminal EventLab handoff state, because the race detector can already be in-race when V4 resumes from a loading/idle state.
- `tests/test_v4_mode3.py`: added regression coverage for the farm watchdog stop path.

Verification:
```powershell
python -m pytest tests\test_v3_vision.py::test_eventlab_filter_state_reads_favorite_checkbox tests\test_v3_vision.py::test_checkbox_detection_ignores_empty_border_and_requires_tick tests\test_v4_mode3.py -q
# 16 passed

python -m pytest -q
# 74 passed, 22 skipped

.\build_v4.bat
# V4 build complete: dist\Forza6HelperV4.exe

dist\Forza6HelperV4.exe --title Forza --skip-buy --skip-farm --auto-focus --watchdog-seconds 20
# completed; dismissed controller-disconnected prompt twice, then reached racing/world-map handoff

dist\Forza6HelperV4.exe --title Forza --skip-buy --farm-seconds 2 --auto-focus --watchdog-seconds 4 --no-exit-after-farm
# completed; farm watchdog stopped SmartRunner after target+4s and no Forza6HelperV4.exe process remained
```

Current status:
- `dist\Forza6HelperV4.exe` is rebuilt at `2026-05-29 08:44`.
- Latest report: `reports\v4_mode3_latest.json`.
- No V1 stable main-flow file was intentionally edited.
- Full real mode-three run is still not certified end-to-end; current validated path is route handoff plus short farm watchdog behavior. The game was not left with a helper process running.

## 2026-05-29 V4 - Vision-guided mode-three runner draft

User requested a complete V4 that uses the current V3 recognition layer to run V1 mode 3, with a two-minute anti-stall guard: if V4 cannot recognize progress and would get stuck, it must stop/recover safely instead of blindly pressing.

Changes:
- Added `v4/` as an independent package; V1 stable files are not edited.
- `v4/recognizer.py`: wraps window capture, OCR, V3 HybridVisionRecognizer, and V1 race detector into one `V4Snapshot`.
- `v4/decision.py`: pure decision layer for mode-three navigation. It explicitly separates EventLab top-tab navigation from `Y` favorite toggling, and gates EventLab car selection on 22B.
- `v4/watchdog.py`: semantic progress watchdog. Default timeout is 120 seconds, with limited recovery attempts.
- `v4/mode3_runner.py`: executable runner. It reuses V1 `BuyCarRunner` for buy/skill phase and V1 `SmartRunner` for farming, but the EventLab route is V3-guided and one-button-then-verify.
- Added `v4_launcher.py`, `README_V4.md`, `Forza6HelperV4.spec`, and `build_v4.bat`.
- Added `tests/test_v4_mode3.py` for button mapping, EventLab top-nav safety, favorite checkbox action gating, 22B gating, and watchdog behavior.

Current V4 safety rules:
- EventLab event list: `Y` is never used as navigation; only LB/RB can move toward `我的收藏`.
- Event selection: press `A` only when selected title matches `SP Farm / 24 second race = 10 skillpoints`.
- Vehicle filter: press `A` only when `收藏` is focused and checkbox is visibly unchecked; if checked, press `B`.
- Vehicle selection: press `A` only when selected car is `IMPREZA 22B-STI VERSION` / 22B.
- Unknown modal: do not press `A` unless text/button semantics are known.
- Default foreground policy: no KeepActive/fake-focus. If Forza is not foreground, V4 stops unless explicitly run with `--auto-focus` or `--allow-background`.

Verification so far:
```powershell
python -m py_compile v4\__init__.py v4\decision.py v4\watchdog.py v4\recognizer.py v4\mode3_runner.py v4_launcher.py
# passed

python -m pytest tests/test_v2_semantic.py tests/test_v3_vision.py tests/test_v4_mode3.py -q
# 61 passed, 22 skipped

python -m pytest tests/test_v4_mode3.py tests/test_v3_vision.py -q
# 44 passed
```

Latest smoke observation:
- `reports\v4_recognizer_smoke_latest.json` was written.
- Current window smoke recognized V3 `idle_showcase` while V1 race detector reported `controller_disconnected`; V4 now prioritizes the V1 controller-disconnected signal for a single verified `A` recovery when V3 is otherwise idle/unknown/loading/modal.

Next required step for this goal:
1. Run the latest rebuilt `dist\Forza6HelperV4.exe` through a controlled V4 route/farm validation after the checkbox and locked-modal hotfix below.
2. Then run the full V4 mode-three cycle. Do not mark the goal complete until the full run is actually verified or the run stops with a concrete V4 attention report.

## 2026-05-29 hotfix 11 - V4 filter checkbox and locked modal recovery

User showed that the EventLab filter page still felt unreliable: the empty `收藏` checkbox and checked `收藏` checkbox need to be read from the small square itself, not inferred from OCR text. User also previously hit a `功能尚未解锁` modal during V4 navigation; stopping was safe, but V4 should close that known non-destructive modal with `B` instead of waiting forever.

Changes:
- `v3/buying_ui.py`: tightened `_checkbox_is_checked` again. It now uses a neutral-light mask, locates the checkbox square, strips the outer border, and requires a real interior checkmark-shaped signal. Empty white borders should no longer count as checked.
- `v4/decision.py`: `eventlab_home` no longer presses `A` if V2 still thinks the active pause tab is something like `在线`; it waits for a confirmed EventLab focus instead.
- `v4/decision.py`: known locked/unavailable modal text such as `功能尚未解锁` now maps to a safe `B` close action, with verification back to the previous page.
- `tests/test_v4_mode3.py`: added coverage for EventLab-home tab mismatch and locked-modal close behavior.
- Rebuilt `dist\Forza6HelperV4.exe`.

Verification:
```powershell
python -m pytest tests/test_v3_vision.py::test_eventlab_filter_state_reads_favorite_checkbox tests/test_v3_vision.py::test_checkbox_detection_ignores_empty_border_and_requires_tick tests/test_v4_mode3.py -q
# 12 passed

python -m pytest -q
# 70 passed, 22 skipped

.\build_v4.bat
# V4 build complete: dist\Forza6HelperV4.exe

dist\Forza6HelperV4.exe --help
# CLI help printed successfully
```

## 2026-05-29 hotfix 10 - EventLab filter checkbox checkmark detection

User showed two EventLab filter screenshots where the focused `收藏` checkbox was visually empty vs checked, but Vision still reported `收藏=已勾选` in both cases. Root cause: `_checkbox_is_checked` treated any white pixels near the center crop as a checkmark, so a slightly shifted crop could count the empty checkbox border as checked.

Changes:
- `v3/buying_ui.py`: `_checkbox_is_checked` now expands the approximate checkbox area, locates the near-square white checkbox component, removes the outer border, then checks for enough white pixels in the interior checkmark area.
- `v3/buying_ui.py`: added small geometry helpers for checkbox crop expansion and component localization.
- `tests/test_v3_vision.py`: added a direct regression test proving an empty white checkbox border is `False`, while the same checkbox with a tick stroke is `True`.

Verification:
```powershell
python -m pytest tests/test_v3_vision.py tests/test_v2_semantic.py -q
# 54 passed, 22 skipped

python -m pytest -q
# 60 passed, 22 skipped

python -m compileall v2 v3 -q
# passed
```

Expected runtime behavior:
- Empty `收藏` checkbox: `筛选状态: 焦点=收藏 收藏=未勾选`, action recommendation should be one `A` to toggle it.
- Checked `收藏` checkbox: `筛选状态: 焦点=收藏 收藏=已勾选`, action recommendation should be `B` to return; do not press `A` again.

## 2026-05-29 hotfix 9 - EventLab top-nav focus and safe tab navigation

User pointed out that the EventLab event-list page must pay attention to the top navigation bar, not only the selected event card. Without the active tab, the recognizer cannot know whether the next safe step is to move LB/RB toward `我的收藏`, wait, or select the current card.

Changes:
- `v2/semantic.py`: EventLab tab OCR scan now covers the real top-nav band (`0.07..0.26` content-relative y). This catches tabs such as `热门`, `最新最热`, `最爱的创作者`, and `我的收藏` in the event-list layout.
- `v2/semantic.py`: when OCR returns repeated tab labels, tab candidates now choose by visual active state first: black active-tab background plus yellow/green underline beats plain OCR confidence.
- `v3/hybrid.py`: EventLab event-list actions now use `active_tab` and visible tab positions. If the current tab is not `我的收藏`, the recommendation becomes one verified `LB`/`RB` step toward `我的收藏`; `Y` is explicitly treated only as "toggle current event favorite", not as navigation.
- `v3/hybrid.py`: if the active EventLab tab is unknown, actions stay at "do not press" until the top nav is recognized.
- `v3/focus_regions.py`: added a pure-numpy focus-box fallback when `cv2` is unavailable, so yellow/green focus detection still works on machines with a thinner Python/OpenCV install.
- `tests/test_v2_semantic.py`: added a regression test for repeated `热门` OCR where only the visually active tab should win.
- `tests/test_v3_vision.py`: added a regression test that EventLab list recommendations prefer top-nav `RB/LB` before card selection when not already on `我的收藏`.

Verification:
```powershell
python -m pytest -q
# 59 passed, 22 skipped

python -m compileall v2 v3 -q
# passed

.\.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --model v3\models\forza_ui_yolo.onnx --scales 1.0 --raw-root datasets\forza_ui\raw --raw-max 80 --output-dir reports
# reports\vision_benchmark_20260529-065319.md
# Raw YOLO label recall=0.963, Raw Hybrid label recall=1.000, Raw Hybrid mean=59.57 ms

.\.venv\Scripts\python.exe -m v3.runtime_selftest --output reports\vision_runtime_selftest_nav_tabs_source.json
# ok=true, provider=CPUExecutionProvider

.\build_vision.bat
# rebuilt dist\Forza6HelperVision.exe, size=117723762 bytes

Start-Process -FilePath .\dist\Forza6HelperVision.exe -ArgumentList @('--self-test','--output','reports\vision_runtime_selftest_packaged_nav_tabs.json') -Wait
# ok=true, provider=CPUExecutionProvider
```

Current runtime state:
- `dist\Forza6HelperVision.exe` was rebuilt and relaunched.
- `reports\gamepad_bridge_status.json` still says `"running": false`; no live game input was resumed during this hotfix.
- On the user's current EventLab event-list screenshot, the expected improved behavior is: `分页` should resolve to the black active top tab such as `热门`; if the target event is not selected and the active tab is not `我的收藏`, action advice should be a single verified `LB` or `RB` navigation step rather than `A` or `Y`.

## 2026-05-29 hotfix 8 - Mode-three path audit, EventLab target title, and favorite-filter safety

User asked to stop treating EventLab `Y` as a navigation action and to model the real mode-three path more strictly: EventLab event selection must target the known favorite `SP Farm / 24 second race = 10 skillpoints`; EventLab car selection must use the 22B; the car filter popup must press `A` on `收藏` only when the checkbox is not already checked, then press `B` after the checkmark is visible.

Mode-three/V1 flow read from code:
- Mode 1 is `SmartRunner` EventLab farming.
- Mode 2 is `BuyCarRunner` 22B buying + skill-mastery spending.
- Mode 3 is `ComboRunner`: buy/spend points until `skill_points_exhausted`, then back out to free roam/pause, enter Creative Hub -> EventLab -> favorite event -> single player -> my cars -> favorite filter -> 22B -> race menu, then hand off to mode 1.

Live/manual flow coverage this pass:
- Bought-path samples: `vehicle_buy_grid`, `design_grid`, `color_select`, `car_preview`, `purchase_confirm`, post-purchase `idle_showcase`/`loading_transition`.
- Mastery-path samples: `pause_vehicle_entry`, `vehicle_mastery`, `skill_points_exhausted`.
- EventLab-path samples: `eventlab_home`, `eventlab_events`, `eventlab_favorites`, `eventlab_race_type`, `eventlab_my_cars`, and `race_menu`.
- Important captured examples include:
  - `datasets\forza_ui\raw\20260529-054934-329_eventlab_favorites_eventlab`
  - `datasets\forza_ui\raw\20260529-054423-097_eventlab_my_cars_IMPREZA-22B-STI-VERSION`
  - `datasets\forza_ui\raw\20260529-054533-683_pause_story_sample` (now covered as pre-race `race_menu`)
  - `datasets\forza_ui\raw\20260529-050856-427_modal_warning_sample` (skill points exhausted modal)

Changes:
- `v3/buying_ui.py`: added EventLab event-card title extraction. The selected favorite card now resolves to titles such as `SP Farm / 24 second race = 10 skillpoints` instead of generic `eventlab`.
- `v3/buying_ui.py`: added visual `eventlab_filter` checkbox-state reading for the focused `收藏` row.
- `v3/buying_ui.py`: expanded bottom hint parsing for `创建者信息`, `赛事选项`, and `查看赛事信息`.
- `v3/hybrid.py`: EventLab event-list actions now refuse `A` unless the selected title matches the target SP Farm skill-point event. It explicitly notes that `Y` only toggles the current event favorite state.
- `v3/hybrid.py`: EventLab my-cars actions now refuse `A` unless the selected vehicle is `IMPREZA 22B-STI VERSION`.
- `v3/hybrid.py` and `v3/types.py`: output `filter_state`; GUI text can show `筛选状态: 焦点=收藏 收藏=已勾选/未勾选`.
- `v2/semantic.py` and `v3/ui_tree.py`: EventLab tab order expanded to `精选 / 热门 / 本月最佳 / 最新最热 / 全新 / 最爱的创作者 / 我的收藏 / 我的历史记录`; `eventlab_favorites` defaults active tab to `我的收藏` when tab OCR is weak.
- `tests/test_v3_vision.py`: regression tests for EventLab title extraction, favorite checkbox state, safe filter actions, target-event gating, and target-22B gating.

Operational caution:
- After the user corrected the mistaken `Y` behavior, the virtual gamepad bridge was stopped. `reports\gamepad_bridge_status.json` currently says `"running": false`.
- Do not resume live game input from this state unless explicitly requested. The recognition layer and docs can be worked safely from saved samples and user-provided screenshots.

Verification:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 57 passed, 22 skipped

.\.venv\Scripts\python.exe -m v3.dataset --no-augment
# raw_samples=993, images=993, labeled_images=775

.\.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --model v3\models\forza_ui_yolo.onnx --scales 1.0 --raw-root datasets\forza_ui\raw --raw-max 80 --output-dir reports
# reports\vision_benchmark_20260529-062121.md
# Raw YOLO label recall=0.963, Raw Hybrid label recall=1.000, Raw Hybrid mean=54.15 ms

.\build_vision.bat
# rebuilt dist\Forza6HelperVision.exe, size=117721098 bytes

Start-Process -FilePath .\dist\Forza6HelperVision.exe -ArgumentList @('--self-test','--output','reports\vision_runtime_selftest_packaged_eventlab_filter.json') -Wait
# ok=true, provider=CPUExecutionProvider
```

Remaining risk / next samples:
- No local raw sample yet contains the EventLab filter popup with `收藏` unchecked and checked from the current run. The checkbox detector is covered by synthetic regression tests and V1 already had a pixel heuristic, but real samples should be collected before connecting this decision to any runner.
- Vehicle mastery node names are still incomplete for some selected skill nodes; OCR may see blank node areas. Keep using page structure + post-press verification rather than relying on every node title.
- Do not wire these V3 target-action rules back into V1 stable runner yet. They are good as Vision recommendations and as a future replacement for the brittle V1 mode-three detection.

## 2026-05-29 hotfix 7 - Buy-vehicle grid, manufacturer list, button hints, and sampler

User asked to strengthen the complex buy-car page: bottom button hints must be recognized, the right-side manufacturer scrollbar matters, the UI tree should separate `暂停菜单 -> 车辆 -> 购买新车与二手车` from EventLab car selection, and samples should cover different vehicle/manufacturer focus states without buying.

Changes:
- `v3/buying_ui.py`: new parser for buy-car bottom controls, manufacturer name coverage, vehicle-name canonicalization, and manufacturer scroll-state inference.
- `v2/semantic.py`: added `vehicle_buy_grid` and `manufacturer_grid`. The manufacturer page now requires the upper/title area to actually say `制造商`, preventing the vehicle grid's bottom `前往制造商` hint from being misread as the manufacturer list.
- `v3/hybrid.py`: outputs structured `control_hints` and `scroll_state`, reads `manufacturer_focus` / `vehicle_grid_focus` OCR regions, keeps `my_cars_card_focus` as the YOLO card signal, and maps the 22B card to `IMPREZA 22B-STI VERSION`.
- `v3/ui_tree.py`: added `autoshow_showroom`, `vehicle_buy_grid`, and `manufacturer_grid` nodes under `暂停菜单 > 暂停菜单 / 车辆 > 购买与出售`.
- `v3/vehicle_grid_sampler.py`: new safe sampler for vehicle grids and manufacturer lists. It defaults to vgamepad, has a keyboard mode for pages showing keyboard hints, can click the Forza title bar as a real foreground action, and never presses A to buy. A/Enter is only allowed for the narrow `控制器未连接` dismissal case.
- `v3/sample_collector.py` and `v3/gui_v3.py`: raw metadata can now include extra V3 understanding data when saving samples.
- `tests/test_v3_vision.py`: added regression coverage for vehicle-buy grid vs autoshow, manufacturer grid naming, bottom control parsing, and UI-tree nodes.

Live sampling:
```powershell
.\.venv\Scripts\python.exe -m v3.vehicle_grid_sampler --title Forza --input-mode keyboard --click-titlebar --max-steps 14 --settle 0.85
# saved 15 samples, including vehicle grid with selected IMPREZA 22B-STI VERSION and manufacturer focus states:
# PLYMOUTH, PENHALL, RADICAL, RJ ANDERSON, TVR, SRT, SIERRA CARS, ZENVO, etc.

.\.venv\Scripts\python.exe -m v3.vehicle_grid_sampler --title Forza --input-mode keyboard --click-titlebar --no-open-manufacturer --sequence dpad_down,dpad_down,dpad_down --max-steps 16 --settle 0.65
# saved additional manufacturer-scroll samples; scroll_state visible=true position=middle up=true down=true.
```

Important live note:
- The current game showed `控制器未连接` after creating/destroying vgamepad. The sampler's vgamepad A did not dismiss it in this state, so for this local sampling pass keyboard mode was used after a real title-bar click. This is sampling-only; the formal runner should still prefer persistent ViGEm/vgamepad and avoid fake focus.

Verification:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 62 passed, 6 skipped

.\.venv\Scripts\python.exe -m v3.dataset --no-augment
# raw_samples=911, images=911, labeled_images=723

.\.venv\Scripts\python.exe -m v3.runtime_selftest --output reports\vision_runtime_selftest_vehicle_grid.json
# ok=true, provider=CPUExecutionProvider

.\.venv\Scripts\python.exe -m v3.ui_tree --output reports\ui_navigation_tree.md
# exported reports\ui_navigation_tree.md

.\.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --raw-root datasets\forza_ui\raw --raw-max 80 --scales 1.0,0.75 --output-dir reports
# reports\vision_benchmark_20260529-023910.md
# Raw YOLO label recall=0.963, Raw Hybrid label recall=1.000, Raw Hybrid mean=48.57 ms

.\build_vision.bat
# rebuilt dist\Forza6HelperVision.exe, size=117709590 bytes

Start-Process -FilePath .\dist\Forza6HelperVision.exe -ArgumentList @('--self-test','--output','reports\vision_runtime_selftest_packaged_vehicle_grid.json') -Wait
# ok=true, provider=CPUExecutionProvider
```

New reports:
- `reports\vehicle_grid_sampler_latest.json`
- `reports\vehicle_grid_reanalysis_latest.json`
- `reports\vision_runtime_selftest_vehicle_grid.json`
- `reports\vision_runtime_selftest_packaged_vehicle_grid.json`
- `reports\vision_benchmark_20260529-023910.md`

Remaining risk:
- `manufacturer_grid` currently uses OCR/name coverage to infer scrollability. The right scrollbar is visible in screenshots, but visual track/thumb localization still needs a more robust thin-bar detector if exact thumb position becomes necessary.
- The vehicle grid class still reuses the trained `my_cars_card_focus` detector. That is acceptable for runtime fusion, but a future training pass should add more `vehicle_buy_grid`/manufacturer samples and possibly split card-focus classes if the model needs to distinguish EventLab car selection from autoshow purchase grids without OCR.
- Do not wire this buy-car path into V1 runner yet. Keep it in V3 until the target-manufacturer selection and purchase-confirmation steps have enough samples and post-press verification rules.

## 2026-05-29 hotfix 6 - Runtime UI navigation tree and nested tab scope

User pointed out that the top tabs inside `暂停菜单 -> 车辆 -> 购买新车与二手车 -> 购买与出售` are not the same as the pause menu's top tabs. Example: the `剧情` tab on the autoshow/buy-sell page must be interpreted inside that child page, not as `暂停菜单 / 剧情`.

Changes:
- `v3/ui_tree.py`: new runtime UI navigation index. It models screen node, navigation path, tab scope, in-layer options, and child routes. Export command writes `reports\ui_navigation_tree.md`.
- `v3/types.py`: `HybridUnderstanding` now carries `ui_node`, `ui_title`, `navigation_path`, `tab_scope`, `available_tabs`, `available_options`, and `child_routes`; `as_text()` prints them before detections/OCR.
- `v3/hybrid.py`: attaches UI-tree context to every fused result, so `autoshow_buy_sell` displays path `暂停菜单 > 暂停菜单 / 车辆 > 购买与出售` and tab scope `购买与出售顶部分页`.
- `v2/semantic.py`: added `AUTOSHOW_TABS = 剧情 / 购买与出售 / 车辆 / 角色` and keeps them separate from pause menu tabs in the V2 summary.
- `v3/gui_v3.py`: top summary now includes the resolved UI node and tab scope.
- `v3/hybrid.py`: modal focus can now derive the focused button from full-frame OCR plus lime-border scoring. This separates modal title text such as `移动至嘉年华` from focused buttons such as `嗯` / `不`.
- `tests/test_v3_vision.py`: added regression tests for modal button focus from OCR+border, autoshow UI tree scope, and V2 autoshow child tabs.

Verification:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 58 passed, 6 skipped

.\.venv\Scripts\python.exe -m v3.runtime_selftest --output reports\vision_runtime_selftest_source_ui_tree.json
# ok=true, provider=CPUExecutionProvider

.\.venv\Scripts\python.exe -m v3.ui_tree --output reports\ui_navigation_tree.md
# exports the current runtime UI tree

.\build_vision.bat
# rebuilt dist\Forza6HelperVision.exe, size=117696985 bytes

Start-Process -FilePath .\dist\Forza6HelperVision.exe -ArgumentList @('--self-test','--output','reports\vision_runtime_selftest_packaged_ui_tree.json') -Wait
# ok=true, provider=CPUExecutionProvider
```

Important interpretation:
- The tree is intentionally local/sample-backed, not web-scraped. Web results for game UI are incomplete and often stale; real screenshots/samples remain the source of truth.
- The current tree covers the production-critical path: free roam/idle, pause tabs, vehicle page, autoshow buy-sell, garage/my cars, vehicle mastery, my horizon, online, creative hub, EventLab, filters, race type, my cars, race menu/HUD/result/next, modal warnings, maps/settings/tuning/overlays.
- It is not yet a full encyclopedia of every Forza UI. Unknown child pages should be sampled and added as nodes instead of guessing.

## 2026-05-28 hotfix 5 - UI name audit and broad fallback guard

User wanted the program side to use stable official UI names, not the first OCR token from a card. The concrete example was EventLab: OCR may read `HORIZON | eventlab | BFGoodrich | ALUMICRAFT | CR | 创建并浏览赛事`, but the focused card should display `eventlab`.

Changes:
- `v3/ui_names.py`: expanded canonical names for EventLab cards, story page, vehicle page, my horizon, online, store/autoshow, modal titles, race menu/result, and post-race next cards.
- `v3/ui_names.py`: normalization now strips more OCR separators such as parentheses, brackets, `*`, `#`, and Chinese title brackets, so `(HORIZON` / `STEAM*` style fragments do not become selected names.
- `v3/hybrid.py`: skips `rule-fallback` full-page focus boxes when reading small OCR for `selected_item`. This prevents a broad fallback box from turning a whole pause page into `festival` or another background token.
- `v3/ui_name_audit.py`: audits raw sample metadata against the canonical UI name table and treats `rule-fallback` rows as V2 context rows instead of blindly resolving from full-page OCR.
- `tests/test_v3_vision.py`: added regression tests for EventLab, Horizon Play, premium store bundle, Festival Playlist, split vehicle names, online friends, creative hub props, and broad fallback guard.

Verification:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 55 passed, 6 skipped

.\.venv\Scripts\python.exe -m v3.ui_name_audit --raw-root datasets\forza_ui\raw --output reports\ui_name_audit_latest.json
# raw samples=871, candidate rows=724, official name rows=455, fallback rows=127, unresolved rows=142

.\.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --model v3\models\forza_ui_yolo.onnx --scales 1.0,0.65,1.25 --raw-root datasets\forza_ui\raw --raw-max 200 --output-dir reports
# reports\vision_benchmark_20260529-000819.md
# Raw YOLO label recall=0.985, Raw Hybrid label recall=1.000, Raw Hybrid mean=67.43 ms

.\build_vision.bat
# rebuilt dist\Forza6HelperVision.exe, size=117685049 bytes

Start-Process -FilePath .\dist\Forza6HelperVision.exe -ArgumentList @('--self-test','--output','reports\vision_runtime_selftest_packaged_ui_names.json') -Wait
# ok=true, provider=CPUExecutionProvider
```

Remaining risk:
- `vehicle_mastery_focus` often has blank OCR inside skill nodes; runtime should keep the V2 selected skill name when available.
- Some `modal_warning` fallback rows are actually world-map/race-card text captured after modal transitions. Do not add those as modal names; collect more true yes/no modal samples instead.
- The full OCR benchmark with `--with-ocr --ocr-max 2` is still very slow and should be run only for milestone checks. The latest full OCR baseline remains `reports\vision_benchmark_20260528-223830.md`.

## 2026-05-28 hotfix 4 - Canonical UI names

User pointed out that the program should not call the focused EventLab tile `HORIZON` just because OCR reads decorative/brand text first. The recognizer now has a canonical UI naming layer.

Changes:
- `v3/ui_names.py`: new fixed-name resolver. It filters decorative/background OCR tokens such as `HORIZON`, `BFGoodrich`, `ALUMICRAFT`, `CR`, button hints, and generic verbs before falling back to raw OCR text.
- `v3/hybrid.py`: selected item fusion now calls the fixed-name resolver with the OCR region type. Example: `HORIZON | eventlab | BFGoodrich | ALUMICRAFT | CR | 创建并浏览赛事` resolves to `eventlab`.
- `v3/ui_names.py`: added initial fixed-name coverage for story, vehicle, creative hub/EventLab, my horizon, online, store/autoshow, modal, and modal button/menu-row focus regions.
- `v3/hybrid.py`: `eventlab_card_focus` no longer forces the screen to `eventlab_favorites`; it preserves the V2 EventLab/creative-hub screen family where available and uses YOLO as the card/focus signal.

Verification:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 51 passed, 6 skipped
```

Live current-window check after this change was on the vehicle page rather than the EventLab tile, and the saved JSON showed the selected item normalized to `更换车辆` from OCR text split as `更换 | 车辆`.

## 2026-05-28 hotfix 3 - Idle showcase wake probes

User clarified that UI-less vehicle/showroom standby pages are not always true unknown states: pressing `A`, pressing `B`, opening `Menu`, or a small real controller movement can cause the hidden UI to appear. The Vision layer now models this as a wakeable state rather than a dead unknown.

Changes:
- `v3/hybrid.py`: if the fused screen is `unknown`, there are no detections/OCR UI items/focus boxes, and the frame is nonblank with enough visual variance, the screen is promoted to `idle_showcase` at cautious confidence.
- `v3/hybrid.py`: `idle_showcase` returns ordered wake probes: `A`, `B`, then `Menu`, each with a required post-press verification condition. These are action suggestions only in the GUI.
- `v2/semantic.py`: `notification_overlay` now also offers the same cautious wake probes because seasonal notifications often sit on top of a standby/showroom state.
- `v3/hybrid.py`: fixed another fusion issue where final screen could be promoted by YOLO/rules to `modal_warning` while actions still reused stale V2 `unknown` advice. V2 actions are reused only when the V2 screen matches the fused screen family.

Verification:
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_v3_vision.py tests\test_v2_semantic.py -q
# 42 passed, 6 skipped
```

Live no-input check after the action-fusion fix:
- Captured `reports/live_debug/idle_wake_probe_after_action_fix.png`.
- Result: `screen=modal_warning`, `selected_item=已收藏新车！`, provider `CPUExecutionProvider`.
- Action recommendation is now modal-specific `弹窗等待确认`, not stale `未知画面`.

Important boundary: do not implement fake-focus or OS mouse nudging in Vision. If future automation wakes an idle page, prefer normal ViGEm/vgamepad actions (`A`, `B`, `Menu`, or a tiny real stick wiggle) and verify after exactly one probe.

## 2026-05-28 hotfix 2 - Probe OCR, modal/autoshow focus, packaged self-test

User reported more Vision GUI mismatches: modal OCR was readable but the current focused button was not surfaced, autoshow/buy-sell child pages were too coarse, and screenshots still showed stale `ONNX unavailable: model not found`. This pass keeps V1 untouched and strengthens only V2/V3/Vision.

Changes:
- `v3/focus_regions.py`: new yellow-green focus-box detector for button/menu-row outlines.
- `v3/hybrid.py`: when V2/model confidence is low, reads probe OCR regions (`probe_top_center`, `probe_center_modal`, `probe_left_title`, `probe_bottom_hints`) and reruns V2 semantic analysis. Also reads `modal_button_focus` and `autoshow_menu_focus` OCR regions and promotes them into `selected_item`.
- `v2/semantic.py`: added `notification_overlay` for seasonal/system notifications and default selected item for `autoshow_buy_sell`.
- `v3/gui_v3.py`: loads model on startup and overlays OCR regions in the preview, not only detection boxes.
- `v3/runtime_selftest.py` and `vision_launcher.py --self-test`: source and packaged exe can now prove ONNX model resolution/loading without opening the GUI.

Live no-input check on the current Forza window:
- Captured `reports/live_debug/current_after_hotfix.png`.
- Result: `screen=notification_overlay`, `confidence=0.86`, provider `CPUExecutionProvider`, no `model not found`.
- Action recommendation: wait for the seasonal notification to disappear; no blind input.

Verification:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 45 passed, 6 skipped

.\.venv\Scripts\python.exe -m v3.runtime_selftest --output reports\vision_runtime_selftest_source.json
# ok=true

.\build_vision.bat
# rebuilt dist\Forza6HelperVision.exe at 2026-05-28 22:31

Start-Process -FilePath .\dist\Forza6HelperVision.exe -ArgumentList @('--self-test','--output','reports\vision_runtime_selftest_packaged.json') -Wait
# reports\vision_runtime_selftest_packaged.json: ok=true, provider=CPUExecutionProvider

.\.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --model v3\models\forza_ui_yolo.onnx --scales 1.0,0.65,1.25 --with-ocr --ocr-max 2 --raw-root datasets\forza_ui\raw --output-dir reports
# reports\vision_benchmark_20260528-223830.md
```

Latest benchmark summary:
```text
V2 semantic/rule mean: 70.25 ms
YOLO ONNX mean: 56.64 ms
Hybrid mean: 146.52 ms
Full OCR+V2 subset mean: 1721.33 ms
Raw YOLO label recall: 0.971
Raw Hybrid label recall: 1.000
Raw YOLO mean: 41.62 ms
Raw Hybrid mean: 80.19 ms
```

Remaining risk: modal button focus now has rule/OCR support, but more real yes/no modal samples should still be saved because the YOLO class remains generic `modal_warning`; do not connect this directly to V1 runner yet.

## 2026-05-28 hotfix - V3 selected item fusion and packaged model path

Issue observed in the Vision GUI: detection/OCR boxes could be correct while the summary line `selected_item` still showed the broader V2 semantic name. Root cause was fusion priority: V2 semantic `selected_item` was kept ahead of the small-region OCR text attached to the highest-confidence detection box. The packaged GUI also showed `model not found: v3\models\forza_ui_yolo.onnx` when started from `dist`, because the relative ONNX path was resolved against the exe working directory instead of the repo / PyInstaller bundle assets.

Fixes:
- `v3/hybrid.py`: `HybridRecognizer` now promotes small-region OCR text from the primary detection box into `selected_item`, then falls back to V2 semantic text only when no useful detection/OCR text exists.
- `v3/yolo_detector.py`: added `resolve_asset_path()` so model/classes paths resolve from cwd, repo root, PyInstaller `_MEIPASS`, and exe directory.
- `v3/gui_v3.py`: reload checks compare the resolved model path, avoiding false reload/missing-model behavior.
- `tests/test_v3_vision.py`: added regression coverage for OCR-preferred selected item fusion and relative model path resolution.

Verification:
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_v3_vision.py tests\test_v2_semantic.py -q
# 35 passed, 6 skipped

.\build_vision.bat
# rebuilt dist\Forza6HelperVision.exe at 2026-05-28 22:15
```

User-facing expected result: restart `dist\Forza6HelperVision.exe`. On EventLab tiles the summary focus should prefer the visible tile text such as the highlighted tile's OCR, and controller warning should no longer report `ONNX unavailable: model not found`.

## 2026-05-28 final update - V3 Vision race/EventLab sampling and benchmark

本轮在不注入、不 hook、不 fake-focus、不修改游戏文件的前提下，继续推进独立 V3/Vision 识别链路；V1 稳定 runner 未接入、未替换。自动操作只用于用户已授权的采样工具，输入方式为 ViGEmBus/vgamepad 普通虚拟 Xbox 手柄，并保持“按一步、重新识别、验证后再继续”的策略。

新增/强化内容：

- `v3/race_sampler.py`：从 EventLab 赛事页继续导航，采集 `race_menu`、`race_hud`、`race_result`，并写入 `reports\race_sampler_latest.json`。
- `v2/semantic.py`：新增/强化 `eventlab_events`、`race_menu`、`race_result`、`loading_transition`、`free_roam_hud`、`settings_menu`、`tuning_menu`、`online_player_list`、`external_overlay`、`modal_warning` 等页面语义，减少 unknown。
- `v3/focus_sweeper.py`：继续保留危险页保护，避免 Steam/商店/退出游戏等入口被自动进入。
- `benchmarks/benchmark_v3_vision.py`：benchmark 输出 raw per-label recall，便于看纯 YOLO 与 hybrid 的类别弱点。

实采结果：

- raw samples: `871`
- YOLO images: `5226`
- labeled images: `4290`
- raw unknown: `7`
- 新增真实比赛链路样本：`race_menu=19 raw`、`race_hud=19 raw`、`race_result=5 raw`
- 当前数据集摘要：`datasets\forza_ui\yolo\summary.json`

最终主 ONNX：

- 模型文件：`v3\models\forza_ui_yolo.onnx`
- 选择来源：`runs\detect\v3\runs\forza_ui_yolo_race_512_e2\weights\best.pt`
- 选择原因：后续 1 epoch 当前数据集续训虽然把 `race_result` 拉高，但打坏了纯 YOLO 的 `race_menu`；e2 checkpoint 在最终 raw metadata 上更均衡。
- 导出命令：

```powershell
.\.venv\Scripts\python.exe -m v3.train_yolo --checkpoint runs\detect\v3\runs\forza_ui_yolo_race_512_e2\weights\best.pt --imgsz 512 --output v3\models\forza_ui_yolo.onnx
```

最终 benchmark：

```powershell
.\.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --model v3\models\forza_ui_yolo.onnx --scales 1.0,0.65,1.25 --with-ocr --ocr-max 2 --raw-root datasets\forza_ui\raw --output-dir reports
```

报告：`reports\vision_benchmark_20260528-215001.md`

```text
provider: CPUExecutionProvider
V2 semantic/rule mean: 69.80 ms
YOLO ONNX mean: 57.14 ms
Hybrid mean: 146.66 ms
Full OCR+V2 subset mean: 1582.14 ms
V2 focus accuracy: 1.000
Hybrid focus accuracy: 1.000
Raw V3 label cases: 2145
Raw YOLO label recall: 0.971
Raw Hybrid label recall: 1.000
Raw YOLO mean: 43.99 ms
Raw Hybrid mean: 84.13 ms
```

Per-label 注意点：

- `race_menu`: YOLO 1.000, Hybrid 1.000
- `race_result`: YOLO 0.600, Hybrid 1.000，真实 raw 仍只有 5 张，需要继续补样本。
- `pause_creative_hub_focus`: YOLO 0.700, Hybrid 1.000，样本少且与 EventLab 卡片相似。
- `pause_my_horizon_focus`: YOLO 0.706, Hybrid 1.000，仍需更多焦点位置样本。

当前判断：V3/Vision 链路已经具备可验证成果：采集、自动标注、YOLO 数据集、训练/导出、ONNXRuntime CPU 推理、规则/OCR 融合、按键建议验证条件、GUI、benchmark、打包入口均已跑通。由于 `race_result` 和少数暂停分页焦点仍样本不足，暂不建议直接接入 V1 主流程；应继续作为 V3 实验能力使用。

常用命令：

```powershell
.\.venv\Scripts\pythonw.exe vision_launcher.py
.\.venv\Scripts\python.exe -m v3.race_sampler --title Forza --max-steps 520 --settle 0.9 --hold 0.16 --run-seconds 180
.\.venv\Scripts\python.exe -m v3.relabel_raw_samples --raw-root datasets\forza_ui\raw
.\.venv\Scripts\python.exe -m v3.dataset --raw-root datasets\forza_ui\raw --dataset-root datasets\forza_ui\yolo
.\.venv\Scripts\python.exe -m v3.train_yolo --checkpoint runs\detect\v3\runs\forza_ui_yolo_race_512_e2\weights\best.pt --imgsz 512 --output v3\models\forza_ui_yolo.onnx
.\.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --model v3\models\forza_ui_yolo.onnx --scales 1.0,0.65,1.25 --with-ocr --ocr-max 2 --raw-root datasets\forza_ui\raw --output-dir reports
.\build_vision.bat
```

## 2026-05-28 V3 Vision Hybrid Recognizer

### 2026-05-28 late update - Focus-enter sampling and 13-class ONNX

用户允许更大胆地进入每个可见焦点后，新增 `v3/focus_sweeper.py`，用于在暂停页内移动焦点、保存每次高亮状态，并可选择按 A 进入当前焦点后再验证/回退。它只通过 ViGEmBus/vgamepad 发送普通手柄输入，不注入、不 hook、不 fake-focus、不改游戏文件；进入子页面后必须重新识别，不能确认回到暂停页时会写入 `reports\focus_sweep_latest.json` 并停止当前分页。

本轮新增/更新：
- `v2/semantic.py` 识别 `vehicle_mastery` 车辆熟练度技能树页面，避免把技能树误当作车辆暂停页继续循环。
- `v3/types.py` / `v3/candidates.py` / `v3/hybrid.py` 增加 `vehicle_mastery_focus`。
- `v3/yolo_detector.py` 会从 ONNX input shape 自动采用静态输入尺寸；当前模型为 512 输入。
- `v3/focus_sweeper.py` 支持 `--enter-focused` / `--enter-limit`，并增加子页面回退保护。
- `v3/models/classes.txt` 已更新为 13 类。

最新实采和数据集：
- raw samples: `740`
- YOLO images: `4440`
- labeled images: `4014`
- 新增真实覆盖：车辆熟练度技能树、EventLab 我的车辆/22B 卡片、赛后下一站、更多暂停分页焦点进入状态。
- 数据集类别计数：`pause_story_focus=810`, `pause_vehicle_focus=432`, `pause_creative_hub_focus=60`, `eventlab_card_focus=228`, `my_cars_card_focus=42`, `vehicle_mastery_focus=642`, `post_race_next=24`, `modal_warning=912`, `pause_my_horizon_focus=204`, `pause_online_focus=462`, `pause_store_focus=252`。
- 仍为 0 的类别：`race_menu`, `race_result`。不要宣称这两类模型已可用；需要真实比赛 HUD/结算页样本。

最新训练：
```powershell
.\.venv\Scripts\python.exe -m v3.train_yolo --data datasets\forza_ui\yolo\data.yaml --epochs 1 --batch 4 --device cpu --imgsz 512 --name forza_ui_yolo_focus_enter_512 --output v3\models\forza_ui_yolo.onnx
```

结果：`v3\models\forza_ui_yolo.onnx` 已导出，大小约 11.6 MB。验证集整体 `precision=0.729`, `recall=0.687`, `mAP50=0.812`, `mAP50-95=0.712`。`vehicle_mastery_focus` 很强，`post_race_next` 样本太少，`my_cars_card_focus` 验证召回不稳。

最新 benchmark：
```powershell
.\.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --model v3\models\forza_ui_yolo.onnx --scales 1.0,0.65,1.35 --with-ocr --ocr-max 2 --raw-root datasets\forza_ui\raw
```

报告：`reports/vision_benchmark_20260528-191039.md`

```text
cases: 24
raw label cases: 2007
provider: CPUExecutionProvider
V2 semantic/rule mean: 79.79 ms
YOLO ONNX mean: 65.48 ms
Hybrid mean: 177.24 ms
Full OCR+V2 subset mean: 1925.13 ms
V2 focus accuracy: 1.000
Hybrid focus accuracy: 1.000
Raw YOLO label recall: 0.927
Raw Hybrid label recall: 1.000
Raw YOLO mean: 46.84 ms
Raw Hybrid mean: 93.77 ms
```

当前判断：V3/Vision 链路已达到可验证成果：采集、焦点进入采样、自动标注、YOLO 数据集、CPU 训练、ONNX 导出/加载、混合推理、benchmark、GUI 和打包入口都可运行。仍不建议接入 V1 runner，原因是 race/result 未采样、`post_race_next` 和 `my_cars_card_focus` 样本太少，且第二轮 focus sweep 报告里仍有若干 `unknown` 子页面，需要继续补语义规则和样本。

本轮目标：在不注入、不 hook、不 fake-focus、不修改游戏文件、不发送输入的前提下，把“最强识别版”作为独立 V3/Vision 链路落地，先证明采集、数据集、训练、ONNX 推理、混合理解、benchmark 和打包都能跑通，再决定是否有资格接入正式 runner。

保护现状：

- 未改 V1 主流程 runner 文件：`runner.py`、`smart_runner.py`、`combo_runner.py`、`buy_car_runner.py`、`buy_car_detector.py`、`screen_detector.py` 等稳定版入口没有被本轮改动。
- 新增内容集中在 `v3/`、`benchmarks/`、`README_VISION.md`、`vision_launcher.py`、`Forza6HelperVision.spec`、`build_vision.bat`、`requirements_vision.txt` 和 `tests/test_v3_vision.py`。
- V3 GUI 只识别、显示建议、保存样本，不连接虚拟手柄，不发送任何按键。

已完成能力：

- `v3/sample_collector.py`：支持 live window capture 和本地截图导入，raw 样本保存到 `datasets/forza_ui/raw/`。每个样本包含 `image.png`、窗口尺寸/标题/时间/采集方式、OCR 原始结果、V2 页面理解结果、自动候选框和 `metadata.json`。
- `v3/candidates.py`：复用 V2 黄绿/亮黄焦点框检测，输出统一 `VisionDetection`，可直接转 YOLO label。
- `v3/dataset.py`：从 raw 样本生成 YOLO 数据集，包含 `images/train`、`images/val`、`labels/train`、`labels/val`、`data.yaml` 和 `summary.json`；增强包含 blur、brightness、contrast、crop、scale。
- `v3/train_yolo.py`：提供 Ultralytics YOLO nano 训练与 ONNX 导出入口，并支持从已有 `.pt` checkpoint 单独导出 ONNX。
- `v3/export_bootstrap_onnx.py`：生成 `v3/models/bootstrap_empty.onnx`，用于无训练模型时验证 ONNXRuntime/打包链路。
- `v3/yolo_detector.py`：ONNXRuntime 推理层，默认 CPU，可选 DirectML provider；支持 Ultralytics 常见输出形状。
- `v3/hybrid.py`：融合 YOLO/ONNX、规则候选、V2 语义和 OCR 小区域，统一输出 `HybridUnderstanding` / `ActionRecommendation`；动作建议都带 verify 条件，不确定时输出“不按键/等待重新识别”。
- `v3/gui_v3.py` + `vision_launcher.py`：新 Vision GUI，支持识别一次、实时识别、保存训练样本、生成 YOLO 数据集、显示检测框/OCR 小区域/动作建议、复制结果。
- `benchmarks/benchmark_v3_vision.py`：对比 V2 语义/规则、YOLO ONNX、V3 hybrid 和全图 OCR+V2 子集耗时，并检查缩放截图焦点准确率。
- `Forza6HelperVision.spec` + `build_vision.bat`：Vision 专用打包入口，exe 名称为 `Forza6HelperVision.exe`，不会覆盖稳定版。
- `v3/auto_sampler.py`：在用户明确允许发送输入后使用 ViGEmBus/vgamepad 做自动采样。每次只按一个键，按完重新识别，验证通过才继续；验证失败会写 `reports\auto_sampler_latest.json` 并停止当前危险分支。

本轮实测产物：

- 从 `C:\Users\fu\Videos\Captures\*.png` 导入 8 个 raw 样本。
- 使用 `v3.auto_sampler` 通过虚拟手柄采到控制器断开弹窗、剧情页、车辆页、我的地平线、在线、创意中心和创意中心 EventLab 焦点区域。
- 生成 YOLO 数据集：`datasets/forza_ui/yolo`，当前 32 个 raw 样本、192 张增强图、180 张有标签。
- 当前类别覆盖：`pause_story_focus=18`、`pause_vehicle_focus=126`、`pause_creative_hub_focus=60`、`modal_warning=30`。
- 当前仍缺：`eventlab_card_focus`、`my_cars_card_focus`、`race_menu`、`race_result`、`post_race_next`。
- 安装训练栈：`onnx`、`ultralytics`、CPU `torch` 等。
- 运行 1 epoch CPU 快速训练，导出 `v3/models/forza_ui_yolo.onnx`。最新自动采样数据训练后验证集 `mAP50=0.24937`、`mAP50-95=0.14019`；`modal_warning` 表现最好，焦点类仍偏弱。
- 同时生成 `v3/models/bootstrap_empty.onnx` 作为空检测 ONNX 兜底。
- benchmark 报告：`reports/vision_benchmark_20260528-084443.md`。
- 打包验证通过：`dist\Forza6HelperVision.exe` 已生成，大小约 115 MB；`dist\README_VISION.txt` 已同步。

Benchmark 摘要：

```text
cases: 16
detector loaded: True
provider: CPUExecutionProvider
V2 semantic/rule mean: 56.83 ms
YOLO ONNX mean: 71.19 ms
Hybrid mean: 140.96 ms
Full OCR+V2 subset mean: 1840.00 ms
V2 focus accuracy: 1.000
Hybrid focus accuracy: 1.000
```

重要结论：

- 当前 YOLO 模型仍不能宣称胜过规则/OCR。自动采样后 mAP50 已经从 0 提高到约 0.249，但类别仍不足，尤其缺 EventLab、车辆收藏、比赛菜单、结算页和赛后下一站。
- 但链路已经可运行：采集 -> 自动标注 -> 数据集 -> 训练 -> ONNX 导出 -> ONNXRuntime 加载 -> 混合理解 -> benchmark -> 打包入口。
- 现在不应接入正式 runner。下一步应该先补样本，覆盖暂停菜单剧情页、创意中心、EventLab、车辆收藏列表、比赛菜单、结算页、赛后下一站页和各种弹窗。

常用命令：

```powershell
.\.venv\Scripts\pythonw.exe vision_launcher.py
.\.venv\Scripts\python.exe -m v3.sample_collector --capture --title Forza
.\.venv\Scripts\python.exe -m v3.sample_collector --import "C:\Users\fu\Videos\Captures\*.png" --limit 8
.\.venv\Scripts\python.exe -m v3.dataset --raw-root datasets\forza_ui\raw --dataset-root datasets\forza_ui\yolo
.\.venv\Scripts\python.exe -m v3.auto_sampler --title Forza --max-steps 45 --settle 1.0 --hold 0.22
.\.venv\Scripts\python.exe -m v3.train_yolo --data datasets\forza_ui\yolo\data.yaml --epochs 1 --batch 2 --device cpu --imgsz 640 --name forza_ui_yolo_quick --output v3\models\forza_ui_yolo.onnx
.\.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --model v3\models\forza_ui_yolo.onnx --scales 1.0,0.65 --with-ocr --ocr-max 2
.\build_vision.bat
```

验证：

```powershell
.\.venv\Scripts\python.exe -m py_compile vision_launcher.py v3\*.py benchmarks\benchmark_v3_vision.py
py -m pytest -q tests\test_v2_semantic.py tests\test_v3_vision.py
```

当前已通过：`24 passed, 6 skipped`。

### 2026-05-28 继续采样：全分页 + 多窗口尺寸

用户允许继续使用 ViGEmBus/vgamepad 进入更多页面后，新增/更新：
- `v3/window_sizer.py`：用 Win32 `SetWindowPos` 调整 Forza 窗口尺寸，便于同一页面在中等窗口和大窗口下复采；不注入、不 hook、不修改游戏文件。
- `v3/relabel_raw_samples.py`：使用 raw metadata 里已有 OCR 原文和当前规则刷新 `understanding` / `candidates`，用于修正旧规则写入的候选框。
- `v3/auto_sampler.py`：暂停分页目标扩展为全部 `剧情 / 车辆 / 我的地平线 / 在线 / 创意中心 / 商店`；保守模式仍按一次、识别一次、验证后继续。
- `v2/semantic.py`：修正“无法加入游戏/注意”顶部联网提示条误判。现在顶部提示不会覆盖底层暂停页；真正居中搜索结果/警告仍识别为 `modal_warning`。
- `v3/types.py` / `v3/candidates.py` / `v3/hybrid.py`：新增 `pause_my_horizon_focus`、`pause_online_focus`、`pause_store_focus`，让全部暂停分页都能生成焦点候选框和 YOLO 标签。
- `benchmarks/benchmark_v3_vision.py`：新增 raw metadata label recall，对保存样本按 `1.0 / 0.65 / 1.35` 缩放评估 YOLO 和 Hybrid 标签召回。

本轮实采：
- 当前中等窗口约 `1189 x 698` 外框，采到剧情、车辆、我的地平线、在线、创意中心/EventLab 首页、商店。
- 大窗口复采使用 `v3.window_sizer --width 1700 --height 1000 --x 40 --y 40`，再次采到上述分页。
- raw 样本总数：`245`。
- YOLO 数据集：`1470` 张增强图，`1470` 张有标签。
- 当前类别计数：`pause_story_focus=78`、`pause_vehicle_focus=180`、`pause_creative_hub_focus=60`、`eventlab_card_focus=102`、`modal_warning=888`、`pause_my_horizon_focus=36`、`pause_online_focus=144`、`pause_store_focus=36`。
- 仍缺：`my_cars_card_focus`、`race_menu`、`race_result`、`post_race_next`。

最新训练：
- 命令：`.\.venv\Scripts\python.exe -m v3.train_yolo --data datasets\forza_ui\yolo\data.yaml --epochs 1 --batch 2 --device cpu --imgsz 640 --name forza_ui_yolo_multisize_tabs --output v3\models\forza_ui_yolo.onnx`
- 验证集整体：`mAP50=0.543`、`mAP50-95=0.491`。
- 类别现状：`modal_warning`、`pause_online_focus`、`eventlab_card_focus` 较强；`pause_story_focus`、`pause_my_horizon_focus` 样本仍少；缺失的比赛/结算类暂不可宣称。

最新 benchmark：
```powershell
.\.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --model v3\models\forza_ui_yolo.onnx --scales 1.0,0.65,1.35 --with-ocr --ocr-max 2 --raw-root datasets\forza_ui\raw --raw-max 120
```

报告：`reports/vision_benchmark_20260528-181335.md`

```text
cases: 24
raw label cases: 360
provider: CPUExecutionProvider
V2 semantic/rule mean: 75.66 ms
YOLO ONNX mean: 77.96 ms
Hybrid mean: 172.37 ms
Full OCR+V2 subset mean: 1664.41 ms
V2 focus accuracy: 1.000
Hybrid focus accuracy: 1.000
Raw YOLO label recall: 0.875
Raw Hybrid label recall: 1.000
Raw YOLO mean: 50.28 ms
Raw Hybrid mean: 64.25 ms
```

当前判断：
- 对“暂停页分页/焦点”这条线，混合方案已经能在当前 raw 样本和缩放样本上覆盖中等窗口与大窗口。
- YOLO 单模型还不能独立替代规则层，因为样本分布偏斜，`modal_warning` 重复样本偏多，比赛/结算/车辆收藏内部样本仍缺。
- 继续采集时应优先补：车辆收藏列表、EventLab 深层赛事列表、比赛开始菜单、赛后结算、赛后下一站。

## 2026-05-28 V2 Page Understanding + YOLO Candidate

本轮目标：不要继续在稳定版 V1 上直接试错，而是把“页面理解”单独做成 V2 测试版；同时评估 YOLO 路线是否值得进入下一阶段。

当前原则：

- **V1 稳定版先冻结**：不要为了 V2 识别实验继续改主程序流程，尤其不要再直接改 `combo_runner.py`、`buy_car_detector.py`、`smart_runner.py`，除非 V2 已经证明更稳。
- **V2 只识别不输入**：V2 不连接虚拟手柄，不按键，不替代稳定版。它只负责截图、OCR/视觉理解、输出页面、焦点和下一步建议。
- **不注入游戏**：仍然不走 hook、fake-focus、注入或修改游戏进程。打包后的正式输入路径仍然优先保留 ViGEmBus + vgamepad 虚拟 Xbox 手柄。

### V1 当前认识

- 用户本机 V1 模式三在正确窗口/分辨率下可以稳定跑数小时。
- 朋友机器最早模式三失效，后来确认与游戏分辨率/窗口尺寸强相关；把游戏分辨率改到和用户本机一致的 `3840 x 2160` 后，1 分钟测试能跑通。
- 朋友后续 60 分钟睡觉测试只跑了约 4 场，说明 V1 仍可能在某些状态页或焦点/窗口条件下卡住。结论不是“手柄失效”，而是当前识别根基仍偏脆弱。
- V1 的现实限制：它依赖 OCR、颜色阈值、固定比例区域、状态机兜底。窗口比例、分辨率、UI 缩放、OCR 质量、亮度/HDR、语言、弹窗、游戏焦点都会影响识别。

### V2 当前文件

- `v2_launcher.py`：启动 V2 测试 GUI。
- `v2/__init__.py`：标记 V2 是单独实验包。
- `v2/gui_v2.py`：V2 GUI，包含“识别一次”“开始实时”“停止”“复制结果”。
- `v2/semantic.py`：页面语义模型，负责把 OCR、布局、颜色焦点框组合成 `PageUnderstanding`。
- `tests/test_v2_semantic.py`：V2 语义层测试，覆盖暂停菜单剧情分页、车辆分页、缩小窗口后的车辆焦点识别。
- `README_V2.md`：V2 使用说明。
- `build_v2.bat` / `Forza6HelperV2.spec`：V2 打包入口。

启动命令：

```powershell
.\.venv\Scripts\pythonw.exe v2_launcher.py
```

打包命令：

```powershell
.\build_v2.bat
```

### V2 已完成的识别能力

- 暂停菜单剧情分页：
  - 能区分顶部分页：`剧情 / 车辆 / 我的地平线 / 在线 / 创意中心 / 商店`。
  - 能识别焦点：`收集簿`、`世界地图`、`下一站`、`设置`、`退出游戏`、`Festival Playlist / 欢迎来到日本`。
  - 第一张“地产”误判已经暴露过：不能只靠 OCR 文本或固定块位，要把焦点亮黄边框作为第一信号。
- 暂停菜单车辆分页：
  - 能识别焦点：`购买新车与二手车`、`更换车辆`、`车辆熟练度`、`秘藏座驾`、`车房宝物`、`礼物掉落箱`、`汽车喇叭`、`调校车辆`。
  - 针对右侧小条目，已加入 OCR 文本邻近匹配和亮黄边组件检测。
  - 针对缩小窗口，测试里已经加入 `max_width=760` 的缩放回放，当前车辆页样本可通过。
- 页面建议层：
  - V2 会输出“只展示、不执行”的动作建议，例如从剧情去车辆分页时建议 `RB`。
  - 建议必须带验证条件，例如按完后重新识别 `active_tab`，不能盲按。

### V2 识别根基

`v2/semantic.py` 当前主要依赖四类信号：

- OCR 文本：RapidOCR 识别页面标题、分页名、按钮名、底部提示。
- 归一化布局：把 OCR 坐标转成内容区域内的 `0..1` 坐标，尽量减少窗口尺寸影响。
- 颜色/边框：检测 Forza 焦点的亮黄绿色边框，不再只猜固定位置。
- 状态语义：先判断页面类型，再在对应页面里解释焦点和下一步动作。

这比 V1 的“状态名 + 局部阈值 + 按键兜底”更接近页面理解，但仍不是最终方案。

### 当前 V2 限制

- 还没有接入稳定版主流程，只是测试识别。
- 仍然用了 OCR；极小窗口、模糊缩放、HDR/过曝、UI 比例异常、遮挡窗口都可能降低识别。
- 目前只重点校准了暂停菜单剧情页和车辆页；EventLab、买车页面、车辆收藏列表、比赛结算页、赛后“下一站”页还需要按同样方法补样本和测试。
- 当前 V2 不负责找 22B。22B 选择仍涉及文本/车辆卡识别，单靠焦点框不够。

### 验证结果

最近一次语义层测试：

```powershell
py -m pytest -q tests\test_v2_semantic.py
```

结果：`19 passed, 6 skipped`。跳过项是旧的剧情页本地校准截图不存在时自动跳过，不代表当前代码失败。当前 `.venv` 没有安装 `pytest`，所以如果要用 `.venv` 跑测试，需要先补开发依赖。

语法检查：

```powershell
.\.venv\Scripts\python.exe -m py_compile .\v2\semantic.py .\v2\gui_v2.py .\v2_launcher.py
```

结果：通过。

### YOLO 可行性判断

YOLO 路线**可以做**，但建议做成“混合视觉模型”，不要幻想纯 YOLO 直接替代所有逻辑。

最适合 YOLO 做的事：

- 检测当前页面大类：暂停菜单、车辆页、创意中心、EventLab 列表、车辆列表、比赛菜单、结算页、赛后下一站页。
- 检测焦点框/高亮框位置。
- 检测关键 UI 卡片：暂停菜单 tile、车辆页 tile、EventLab 赛事卡、车辆卡、弹窗。

不适合纯 YOLO 做的事：

- 读取共享代码、车名、积分、具体 OCR 文本。
- 在朋友收藏列表里泛化识别任意位置的 `22B`，除非仍然配合 OCR 或给 22B 卡片做大量样本。

推荐方案：

- YOLO 负责“看见结构和焦点”：页面类别、tile 类别、焦点框、弹窗。
- OCR 只在必要时读取少量文本：比如 `22B`、`我的收藏`、共享代码、确认弹窗文本。
- 状态机只根据“模型输出 + 验证条件”按键，按完必须重新识别。

### YOLO 性能预期

如果训练一个小模型并导出 ONNX，运行时只喂 640px 或 800px 宽的缩放截图，理论上有机会比 V1 的全量 OCR 更快。原因是 OCR 通常比小目标检测更慢，而且 OCR 对模糊/缩放更敏感。

但是否真的更快必须实测，不能拍脑袋。通过标准建议：

- CPU-only ONNX 推理平均耗时低于当前 V1/V2 OCR 识别耗时。
- 在用户本机、朋友机器、不同窗口大小、不同 UI 缩放下，页面类别和焦点识别准确率明显高于 V1。
- 小窗口不要求每个字可读，但必须能稳定识别页面结构和当前焦点。
- 模型文件可以随 exe 一起打包，程序首次运行无需额外训练。

### YOLO 数据集计划

推荐先做最小数据集，不要一口气训练全流程：

1. 收集截图：从 V2 GUI 增加“保存训练样本”按钮，保存原图和当前识别 JSON。
2. 第一批类别只做页面/焦点结构：
   - `pause_story_focus`
   - `pause_vehicle_focus`
   - `pause_creative_hub_focus`
   - `eventlab_card_focus`
   - `my_cars_card_focus`
   - `race_result`
   - `post_race_next`
   - `modal_warning`
3. 标注方式优先用已有亮黄边检测自动生成候选框，再人工复核，减少手工画框。
4. 训练 YOLO nano/small 级别模型，导出 ONNX。
5. 在 V2 里新增 `v2/yolo_detector.py`，让 YOLO 输出和当前 `PageUnderstanding` 融合。
6. 只有 V2 基准测试赢过 OCR/规则版后，再讨论替换 V1 的识别层。

### 下一步建议

1. 先把 V2 继续补成完整页面理解回放测试：剧情页、车辆页、创意中心、EventLab、车辆收藏、比赛菜单、结算页、赛后下一站。
2. 增加一个样本采集工具：每次识别时可保存截图、OCR、页面理解结果、窗口尺寸。
3. 用这些样本生成 YOLO 初版数据集。
4. 训练小模型并导出 ONNX。
5. 写基准脚本，对比：
   - V1/V2 OCR 识别耗时
   - YOLO ONNX 耗时
   - 混合方案准确率
6. 通过后再把 V2 页面理解层接入正式 runner。

## 2026-05-26 EXE Packaging Prep

本轮目标：把项目准备成能发给朋友的 exe，并把虚拟手柄驱动依赖做成更像产品的提示，而不是只丢一句“自己去装驱动”。

已完成：

- 修复朋友电脑未安装 ViGEmBus 时 exe 直接崩溃的问题：`gamepad.py` 不再顶层导入 `vgamepad`，改为创建手柄时懒加载；`app_controller.py` 在常驻连接和开始运行前都会先检查 ViGEmBus，未就绪只提示安装/重启，不让 PyInstaller 弹 `VIGEM_ERROR_BUS_NOT_FOUND` 崩溃框。
- 缺少 ViGEmBus 时，`gui.py` 现在会首次启动自动弹出安装说明并打开官方安装页；用户仍需手动运行安装包和批准管理员权限。
- `gui.py` 顶部右侧新增 **GitHub / 反馈** 入口，打开 `https://github.com/wenhefu/forzaHorizonScript`，用于查看更新和问题反馈。
- `release\README.txt` 改成中文朋友版说明，包含仓库地址、ViGEmBus 一次性安装、窗口模式、开始前准备、模式时间含义、风险说明和日志位置。
- 新增 `driver_check.py`：启动时用 `sc.exe query ViGEmBus` 检查 ViGEmBus 是否安装并运行。
- `gui.py` 顶部引导区新增虚拟手柄驱动状态和“安装/修复虚拟手柄驱动”按钮；按钮打开官方 release 页面。
- `gamepad.py` 的虚拟手柄创建失败提示追加官方安装页，朋友电脑没装驱动时更容易自救。
- `build.bat` 改为先安装依赖、跑 `compileall` 和单测，再用 PyInstaller 打包；现在会额外 `--collect-all vgamepad`，并把 `release\README.txt` 复制到 `dist\README.txt`。
- 新增 `release\README.txt`，用于和 exe 一起发给朋友，说明 ViGEmBus 一次性安装、窗口模式和风险边界。
- `app_logging.py` 在 PyInstaller onefile 环境下会把日志写到 exe 同目录的 `logs\forza6helper.log`，避免日志落在临时解压目录。

## 2026-05-26 Post-Race Next Page Fix

现场问题：组合模式到达每轮刷图时间后，`SmartRunner` 在结算页按 `A` 退出赛事，随后游戏会进入“下一站”推荐赛事页面。旧逻辑把这个页面误当成暂停菜单，导致组合模式提前进入下一轮并把 `SmartRunner` 启在错误页面上，随后开始反复按十字键上。

已完成：

- `buy_car_detector.py` 新增 `post_race_next` 状态，用 OCR 区分“下一站”推荐页和真正的暂停菜单；真正暂停菜单仍通过“世界地图 / 收集簿 / 剧情 / 车辆 / 创意中心 / 设置”等关键词识别。
- `combo_runner.py` 在回暂停菜单流程中遇到 `post_race_next` 会按 `B` 返回自由漫游，再重新按 `Menu` 打开暂停菜单，不再直接进入下一轮买车。
- `screen_detector.py` 和 `smart_runner.py` 也新增赛后“下一站”页面兜底识别；如果智能刷图模式单独遇到该页，会按 `B` 退回自由漫游，避免继续按上。
- `buy_car_runner.py` 增加独立买车模式的同类恢复：识别到赛后“下一站”页时按 `B` 回自由漫游，再按 `Menu` 打开暂停菜单。
- 新增 `tests/test_post_race_next.py`，覆盖“下一站”推荐页不应识别为暂停菜单，以及真正暂停菜单仍应保持 `buy_pause_menu`。

追加修正：

- 初版把暂停菜单关键词写得过宽，`购买与出售 / 车展` 页会被误判为 `buy_pause_menu`，导致买车阶段不停按 RB。
- 已把 `购买与出售 / 车展 / 拍卖场 / 车辆通行证 / 票券车辆` 的判断放到暂停菜单判断之前，并移除暂停菜单判断里的泛化关键词 `剧情 / 车辆 / 在线 / 创意中心 / 商店 / 设置`。
- `post_race_next` 现在要求“下一站”出现在左上标题位置，避免暂停菜单中间的“下一站”卡片误触发。
- 测试补充覆盖 `购买与出售 / 车展` 不应被识别成暂停菜单。

## 2026-05-26 Wide Prep UI

本轮目标：把窗口从偏正方形调整成横向长方形，并把用户给的三张准备截图放进产品 UI，而不是只写一段说明。

已完成：

- `gui.py` 改成两列布局：左侧保留主操作区，右侧新增 **开始前准备** 卡片。
- 后续按用户反馈继续拉宽窗口，当前预览约 `1495 x 958`，整体更接近横向桌面工具。
- 右侧三步准备清单使用真实截图缩略图，点击缩略图可弹出大图预览。
- 已移除三步准备卡片里的“已完成”勾选，避免普通用户误以为需要逐项打卡才能运行。
- 运行参数会按模式显示：模式一是 **刷图运行时间**，模式三是 **每轮刷图时间**；模式三旁边提示 `推荐 60；0=默认 90；买车不计时`。
- 运行参数不需要保存按钮，点“开始”时读取当前输入；无效输入会自动回填为安全默认值并写日志。启动倒计时无效回到 `5.0`，刷图时间无效回到 `0.0`，负数会钳到 `0.0`。
- 组合模式的时间语义已修正：界面里的“每轮刷图时间”只控制 EventLab 刷图阶段，买车加点阶段不再消耗这个时间，也不会因为这个时间到而中断买车。模式三填 `0` 时会使用 `config.py` 的 `COMBO_EVENTLAB_FARM_SECONDS` 作为每轮刷图默认值。
- 三步文案已按用户原意优化并完整放入界面：
  1. 把加满点数的 `1998 Subaru Impreza 22B-STI` 加入“车库 -> 我的车辆”的收藏，并把当前驾驶车辆设为这台车。
  2. 把刷技能点赛事放进“创意中心 -> 游玩赛事 -> 我的收藏”的第一个位置，推荐共享代码 `890 169 683`。
  3. 开始前停留在暂停菜单的首个分页，也就是上方分页从“剧情 / 车辆 / 我的地平线 / 在线 / 创意中心 / 商店”开始的页面。
- 三张图片已复制到 `assets/prep/`：
  - `vehicle_22b.png`
  - `eventlab_favorite.png`
  - `pause_home.png`
- `build.bat` 已加入 `--add-data "assets;assets"`，打包 exe 时会带上引导截图。
- `README.md` 已同步开始前准备说明。

验证：

- `.venv\Scripts\python.exe -m compileall -q .` 通过。
- `.venv\Scripts\python.exe -m unittest discover -s tests` 通过。
- 本地生成 GUI 预览图 `logs/gui-preview-wide.png`，窗口约 `1253 x 998`，横向布局和右侧准备清单显示正常。

## 2026-05-26 Product UI Pass

本轮目标：把 GUI 从“开发工具面板”调整成更接近 Codex/Claude 桌面版的安静产品感，同时使用地平线暂停菜单近似的深绿色背景。

已完成：

- `gui.py` 重排为顶部标题/引导、运行模式、运行参数、控制、当前模式提示、运行日志几个清晰区域。
- 顶部新增首次使用引导：**设置 -> 视频 -> 亮度 -> 全屏幕：关闭**，提醒用户先把游戏设为窗口模式。
- 默认界面继续只展示模式一/二/三；高级/调试模式、手动按 A/B、识别一次和高级复选框保持折叠。
- 使用深绿色主背景、浅色内容面板、克制按钮和深色日志区，整体更接近产品版桌面工具。
- `README.md` 同步补充窗口模式引导。

验证：

- `.venv\Scripts\python.exe -m compileall -q .` 通过。
- `.venv\Scripts\python.exe -m unittest discover -s tests` 通过。
- 本地生成 GUI 预览图 `logs/gui-preview.png`，窗口约 `940 x 958`，默认调试区折叠，模式提示已正常显示。

## 2026-05-26 Product Shell Refactor

本轮目标是先把“产品版瘦身”的地基打稳，避免只是把控件隐藏、但旧功能仍通过零散变量暗中影响运行。

已完成：

- 新增 `modes.py`：所有运行模式集中登记，包含模式 id、显示名、runner 类型、默认高级选项、提示文案、是否普通界面可见。
- 新增 `settings.py`：GUI 启动一次运行时会生成不可变 `RuntimeSettings` 快照，runner 不再直接从 Tk 变量里读动态状态。
- 新增 `app_controller.py`：集中管理虚拟手柄、`Runner`/`SmartRunner`/`BuyCarRunner`/`ComboRunner` 生命周期、开始/停止、手动按键、识别入口和旧前台计时的焦点恢复回调。
- `gui.py` 现在只负责窗口渲染、输入框、按钮、日志展示和把当前表单转成 `RuntimeSettings`。
- 普通界面默认只展示模式一/二/三；模式四/五、按 A/B、识别一次和高级复选框放入“显示高级/调试模式”，默认折叠但未删除。
- `README.md` 已同步新的产品/调试分层和代码结构说明。

验证：

- `.venv\Scripts\python.exe -m compileall -q .` 通过。
- `.venv\Scripts\python.exe -m unittest discover -s tests` 通过。
- 轻量模块自检通过：`product_modes() == ['skill_points', 'buy_car', 'combo']`，`debug_modes() == ['foreground', 'background']`，`RuntimeSettings.total_seconds` 正常换算。

后续建议：

1. 再做一层“状态事件”输出，让 runner 发 `stage/message/severity`，GUI 显示稳定的状态卡，不再让普通用户读日志判断进度。
2. 给 `buy_car_detector.py` 和 `screen_detector.py` 加截图/识别回放测试，先覆盖这次现场踩过的 EventLab 我的车辆、我的收藏/历史记录 tab、22B 选车。
3. 打包前补 `packaging/` 目录、PyInstaller spec、版本号、图标、ViGEmBus 检测/安装提示。

## 2026-05-26 Mode Three Field Validation

当前最新状态：

- **模式三已现场跑通关键主链路**：买车加点 -> 技术点数不足 -> 自动退回自由漫游/暂停菜单 -> 创意中心 -> EventLab -> 赛事 -> 我的收藏 -> 选择收藏赛事 -> 单人 -> 我的车辆 -> 筛选收藏 -> 选择 22B -> 进入 EventLab 开始赛事菜单 -> 交给模式一刷图。
- 组合模式每轮 EventLab 刷图时长现在由 GUI 的 **每轮刷图时间** 控制，推荐填 60 分钟；填 0 时才使用 `config.py` 的 `COMBO_EVENTLAB_FARM_SECONDS = 90 * 60` 作为默认值。
- 到达每轮刷图时间后，`SmartRunner` 不会立刻打断比赛；它会继续跑到下一次结算页，在原本要按 X 重开的位置改按 A 退出，再交回 `ComboRunner`。
- **尚未现场完整验证**：每轮刷图时间到点后能否稳定等当前比赛结束、按 A 退出、回自由漫游、打开暂停菜单并进入下一轮买车。因为验证周期太长，目前只能确认前半段到刷图入口已成功。

本轮修复过的关键问题：

- EventLab “我的车辆”页在筛选收藏后，顶部会从“当前车辆/购买车辆”变成动态品牌 tab。检测器已改为使用“我的车辆”标题、底部“筛选/前往制造商/排序/切换详情/切换数据”提示和卡片文本综合判断，不再误判为 `buy_sell_menu`。
- 22B 选择不再写死位置，继续使用 OCR 文本列 + 当前高亮列定位，适配朋友收藏列表里 22B 位置不同的情况。
- EventLab 顶部 tab 切到“我的收藏”时，新增 active tab 识别：`7=我的收藏`，`8=我的历史记录`。如果按 RB 过头到历史记录，组合模式会按 LB 回退，而不是继续向右。
- 若 GUI/脚本中途停在 EventLab 页面，模式三重新开始时会尝试从当前 EventLab 中途页续接，不会强行从买车阶段重跑。

当前建议的短期验证：

1. 把 `COMBO_EVENTLAB_FARM_SECONDS` 临时改小，例如 `5 * 60` 或 `10 * 60`，专门验证“刷图到点 -> 等结算 -> A 退出 -> 回暂停菜单 -> 下一轮买车”。
2. 验证通过后再改回 `90 * 60`。
3. 日常使用时仍建议保持 Forza 前台，不要点击其它窗口；失焦时游戏会暂停或进菜单，这是游戏行为，当前工具不通过 hook/injection 绕过。

产品化/打包方向：

- 当前最稳的输入方式仍然是 **ViGEmBus + vgamepad 虚拟 Xbox 手柄**。打包成 exe 可行，但朋友电脑需要安装 ViGEmBus 驱动；exe 本身不能完全免驱替代内核级虚拟手柄。
- 不依赖虚拟手柄的替代方案主要是键盘输入或更底层的窗口/输入注入。键盘方案改动中等，但可靠性大概率更差，尤其是油门长按、菜单按键、焦点切换和 Forza 对后台输入的处理。hook/fake-focus 方案风险高，不建议内置。
- 推荐打包策略：保留虚拟手柄；提供一个正常的 exe，加一个首次运行检查/提示页，检测 ViGEmBus 是否安装并运行，缺失时提示用户安装。

GUI 精简建议：

- 给普通用户保留：运行模式、开始/停止、打开日志、切回游戏、总运行时间、模式三状态提示。
- 把“按A确认/按B返回/识别一次/高级复选框”折叠到“高级/调试”区域，默认隐藏。
- 可以去掉或弱化“模式四/模式五”：它们现在主要是实验/兜底，容易让朋友误选；产品版建议默认只展示模式一、模式二、模式三。

## 2026-05-25 Stable Checkpoint

Workspace: `D:\地平线6脚本`

目前已经现场验证的稳定能力：

- **模式一：刷技能点（EventLab）** 已能通过截图识别循环执行：图 1 开始赛事按 A、比赛中保持油门、结果页按 X、重开确认页按 A，再回到开始赛事页继续。
- **模式二：买车加点（先买 22B）** 已能从暂停菜单进入买车链路，购买斯巴鲁 22B，进入车辆熟练度，按固定 22B 加点路径买到抽奖精灵，然后回到买车入口继续循环。
- 买车链路现在依赖 OCR + 画面颜色双重确认，重点保护点包括：购买新车入口、车展、制造商列表、斯巴鲁品牌、22B 车辆卡、购买确认、车辆页、升级页、车辆熟练度页。
- 当前模式二在技能点不足时会停止，避免无点数时继续误操作。这个“点数不足”页面是下一阶段组合模式的切换点。

当前最重要的安全边界：

- 不注入游戏进程，不做 fake-focus/hook。
- 截图只在内存中处理，不把识别截图落盘。
- 买车路径只有在确认目标是 22B 后才允许进入设计/颜色/购买确认；购买确认若未 armed 会按 B 取消。

下一阶段目标：

- 新增一个组合模式：先跑买车加点，遇到“点数不足”后退出到自由漫游，打开暂停菜单，进入创意中心/EventLab/赛事/我的收藏，启动刷技能点 EventLab；刷够一段时间后再回到买车加点循环。
- 组合模式建议用新的编排 runner 实现，复用 `BuyCarRunner` 和 `SmartRunner` 的检测/输入逻辑，不直接破坏已经验证的模式一、模式二。

## 2026-05-25 Combined Mode Update

已新增 **模式三：买车+刷分组合（实验）**。

当前组合流程：

- 先运行买车加点流程。
- `BuyCarRunner` 现在会把“技术点数不足/不够购买额外加成”识别为明确的 `points_exhausted` 停止原因。
- `ComboRunner` 在该停止原因出现后，按 A 关闭弹窗，连续 B 返回到自由漫游，再按 Menu 打开暂停菜单。
- 组合模式会一边按 RB 一边识别，确认到“创意中心”后停止切 tab，按 A 进入 EventLab。
- 进入 EventLab 后，按 A 到赛事页，再一边按 RB 一边识别，确认到“我的收藏”后按 A。
- 进入收藏赛事后，确认/处理“选择比赛类型”，默认按 A 选“单人”。
- 到“我的车辆”页后按 Y 打开筛选，确认“收藏”被勾选后按 B 返回。
- 在筛选后的车辆列表里，用 OCR 文本和绿色高亮列计算 22B 的位置，只有确认当前高亮是 22B 后才按 A。
- 只有在现有 `SmartRunner` 能识别到 EventLab 开始赛事菜单时，才把控制权交给刷技能点模式；交接后默认固定刷 2 小时。

尚未完成：

- 从刷技能点阶段自动判断“刷够点数了”并回到买车流程。当前组合模式进入 EventLab 后会继续按模式一刷，直到手动停止或总运行时间到。

Date: 2026-05-24
Workspace: `D:\地平线6脚本`
Repository: `https://github.com/wenhefu/forzaHorizonScript.git`

## Current State

The repository was cloned directly into `D:\地平线6脚本` without an extra `forzaHorizonScript` directory.

Local setup completed:

- Created `.venv` in the project directory.
- Installed Python dependencies from `requirements.txt`.
- Installed `pyinstaller` for packaging support.
- Confirmed ViGEmBus is installed and running.
- Confirmed `vgamepad` can create a virtual Xbox 360 controller.

Runtime command:

```powershell
.\.venv\Scripts\python.exe gui.py
```

## Main Problem Investigated

The original goal was to automate a Forza Horizon 6 EventLab loop with a virtual Xbox controller.

The hard blocker is focus behavior:

- Clicking the helper UI makes Forza lose focus.
- Forza may pause, show menus, or show a controller disconnected modal.
- When the game pauses or leaves the race flow, a fixed wall-clock timer becomes wrong.
- In one observed run, the script advanced after the configured 44 seconds, but the actual game result screen showed about 3 minutes, so the script and game state had diverged.

## Research Summary

I checked how PC/AAA games generally handle background running and focus loss.

Findings:

- Clean background execution usually requires the game itself to support background input/running.
- Microsoft GameInput has a focus policy for background input, but it is something the game must opt into.
- Borderless window mode helps only for games that do not pause on focus loss; it is not guaranteed.
- Tools that force games to behave as foreground/background-multiplayer apps usually rely on hook/injection/fake-focus techniques.
- Hook/injection approaches such as Special K, Nucleus/ProtoInput-style fake focus, or similar Windows API interception are riskier around anti-cheat and are not appropriate to casually embed in this helper.

Useful references:

- Microsoft GameInput focus policy: https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/input/gameinput-v0/enums/gameinputfocuspolicy-v0
- Forza forum discussion about pausing on alt-tab/focus loss: https://forums.forza.net/t/please-do-not-pause-with-alt-tab-lose-focus/537904
- Nucleus/ProtoInput fake focus/background input concepts: https://www.splitscreen.me/docs/kbm-setup and https://www.splitscreen.me/docs/proto/
- Special K anti-cheat warning context: https://wiki.special-k.info/en/SpecialK/Global

Conclusion: without injecting/hooking the game process, this helper cannot guarantee that Forza continues running fully in the background.

## Code Changes Made

### Logging

Added `app_logging.py`.

The app now writes persistent logs to:

```text
logs\forza6helper.log
```

The log records:

- Python/platform/package versions.
- ViGEmBus service status.
- Virtual gamepad creation.
- Foreground/focus actions.
- Runner steps and virtual gamepad input.
- Runtime exceptions.

`logs/` was added to `.gitignore`.

### Virtual Controller Lifecycle

Changed the design from "create a virtual gamepad only when Start is pressed" to "create and keep the virtual gamepad connected while the GUI is open."

Reason:

- Forza can show "controller disconnected" when the virtual device appears/disappears.
- Keeping the virtual controller alive should avoid unnecessary device disconnect/reconnect behavior.

`gamepad.py` now:

- Accepts a logger.
- Logs controller operations.
- Uses a lock around `vgamepad` calls.
- Fixes the trigger API call from `value=` to `value_float=`.

### GUI

`gui.py` now includes:

- Persistent virtual controller connection on startup.
- `打开日志` button.
- `切回游戏` button.
- Manual `按A确认` and `按B返回` buttons.
- "游戏模式：点击本窗口不抢焦点" option.
- "开始后自动切回游戏窗口" option.
- "只在游戏前台时计时（失焦自动暂停脚本）" option.
- "切回后按 A 确认/恢复控制器" option, currently default off.

### Focus Handling

Expanded `focus.py` with:

- Window title lookup.
- Current foreground title lookup.
- Forza foreground detection.
- Windows foreground activation using `SetForegroundWindow`, `BringWindowToTop`, `AttachThreadInput`, etc.
- Best-effort no-activate/topmost helper window mode.

Important limitation:

- Windows foreground APIs cannot force true background running.
- The helper can try to bring Forza back to the foreground, but cannot make Forza keep simulating while genuinely backgrounded.

### Runner Behavior

`runner.py` now supports foreground-aware timing:

- If configured, scripted time only advances while Forza is the foreground window.
- When Forza loses focus, the script logs the event and pauses its own timer.
- When Forza returns to foreground, the script continues from the same step instead of blindly advancing to the next lap.

This is the safest non-injection path identified so far.

## Current Recommended Product Direction

Do not try to solve "Forza fully runs in background" inside this helper unless the user explicitly accepts hook/injection risk.

Recommended safe behavior:

- Keep Forza foreground while automation runs.
- If focus is lost, pause the script timer and input sequence.
- Try to bring Forza back to foreground.
- Do not auto-press menu buttons unless explicitly enabled.
- Avoid user interaction with other windows during a run.

## Testing Performed

Verified:

- Python compile check passes:

```powershell
.\.venv\Scripts\python.exe -m compileall -q .
```

- `vgamepad` can create a virtual controller.
- `Gamepad.apply(throttle=1.0)` works after fixing `value_float`.
- Runner can run repeated steps without immediately crashing.
- Foreground-aware runner simulation pauses timing while foreground check returns false and resumes after it returns true.
- GUI starts and creates a persistent virtual gamepad.

## Known Issues / Open Questions

- Actual Forza behavior still needs live validation after the foreground-aware timing change.
- If Forza pauses itself despite being brought back to foreground, the helper cannot infer menu/race state from controller inputs alone.
- The configured `DRIVE_SECONDS = 44.0` may be too short for the user's observed route. One screenshot showed a completed run at `03:00.564`; the drive time may need to be closer to 180-185 seconds.
- The previous global hotkey `Ctrl+Alt+F8` registered successfully, but one user test did not show the hotkey being received while Forza was focused.
- A true "run in background while I use the PC" feature likely requires game support or risky hook/fake-focus tooling.

## Next Steps

1. Test the current foreground-aware build with Forza in the foreground.
2. Confirm logs show "检测到游戏失焦，暂停脚本计时" when focus is intentionally changed.
3. Set `每圈前进时间` to match the actual route duration.
4. Only after safe foreground automation works, decide whether to investigate hook/fake-focus tools separately.
