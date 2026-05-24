# Handoff - Forza Horizon 6 Helper

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
