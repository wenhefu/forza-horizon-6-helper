> ⚠️ **已淘汰，别用。** 命令行版 `Forza6HelperV4.exe` 已被 GUI 版 `Forza6HelperV4GUI.exe`
> 取代（带技术点感知买车、清理重复车、拍卖场抢车）。本文件仅作历史留存，请看根目录 [`README.md`](README.md)。

# Forza6Helper V4 模式三视觉执行版

V4 是独立实验版，不覆盖 V1 稳定版。目标是用 V3 的页面理解来执行 V1 的模式三主线：买 22B/加点到点数不足，然后进入 EventLab 收藏赛事，筛选收藏车辆，确认 22B，进入开始赛事菜单，再交给模式一刷分。

## 2026-05-29 当前验证状态

- 最新完整实跑通过：`dist\Forza6HelperV4.exe --title Forza --farm-seconds 60 --watchdog-seconds 120` 已在 2026-05-29 15:43-15:49 跑完整模式三，报告在 `reports\v4_mode3_latest.json`，结果为 `completed=true`、`stopped_reason=completed`。
- 这次实跑覆盖：控制器弹窗恢复、暂停菜单进入车辆页、移动到嘉年华、车展购买 22B、设计/颜色/购买确认、车辆熟练度、技术点不足弹窗、返回自由漫游、打开暂停菜单、进入 EventLab/race menu、交给 V1 `SmartRunner` 刷分、赛后/自由漫游收尾回到暂停剧情页。
- `SmartRunner` 在 60 秒目标后没有自行平滑退出，V4 的 farm watchdog 在额外 120 秒后接管并停止它，随后完成收尾。这符合“两分钟内无法继续就接手”的要求；报告里的 `farm_watchdog_stop after 180.1s` 是这次保护动作的证据，不是最终失败。
- 当前验证命令：`.\.venv\Scripts\python.exe -m pytest -q` 为 `97 passed, 22 skipped`；`.\build_v4.bat` 已重新生成 `dist\Forza6HelperV4.exe`。
- `dist\Forza6HelperV4.exe` 已重新打包。
- 当前勾选规则：筛选页右侧小方框为空就是未勾选；小方框内部有白色对勾才是已勾选。程序不再只靠 OCR 或焦点行推断 `收藏` 已勾选，GUI 报告会显示“未勾选（空框）/已勾选（有白色对勾）”。
- 赛事/活动中打开暂停菜单时，创意中心、车辆等卡片会带锁。V4 现在把这种画面识别为 `race_pause_menu`，默认按 `B` 返回当前比赛，不会按 `A` 进入锁住的 EventLab/车库布局。
- 已知 `功能尚未解锁` 这类 OK 弹窗用 `A` 关闭；关闭后 V4 会记录锁定状态，后续不会反复进入同一个锁定入口。
- 买车阶段由 V4 语义看门狗监督：稳定卡在世界地图时先按 `B` 关闭地图并重启一次 BuyCarRunner；如果 BuyCarRunner 已经把页面带到 EventLab/比赛路线，V4 会停止 BuyCarRunner 并接管导航。
- 启动预检：如果启动时已经在 `race_hud`、`race_pause_menu` 或 EventLab 路线页，V4 会跳过 BuyCarRunner，直接进入 V4 导航/刷分交接，避免在比赛中误跑买车流程。若预检先被“控制器未连接”弹窗遮住，V4 会先按一次 `A` 清掉弹窗并重新识别，再决定是否允许启动 BuyCarRunner。
- 刷分交接给 V1 `SmartRunner` 后也有 V4 看门狗：到达 `farm_seconds` 后最多再等 `watchdog_seconds`，否则强制停止 SmartRunner、手柄回正并写入 `reports\v4_mode3_latest.json`。
- 历史短验：锁态暂停菜单帧用真实 `.venv` OCR 回放后识别为 `race_pause_menu`，动作建议为 `B`。
- 最终包短验：`dist\Forza6HelperV4.exe --title Forza --farm-seconds 2 --watchdog-seconds 4 --auto-focus --no-exit-after-farm` 已从控制器弹窗预检进入 `smart=racing`，跳过 BuyCarRunner，交给 SmartRunner 后由 V4 farm watchdog 收尾；未留下 `Forza6HelperV4.exe` 进程。

## 边界

- 不注入游戏进程。
- 不 hook。
- 不使用 KeepActive/fake-focus。
- 不修改游戏文件。
- 输入仍使用 ViGEmBus + `vgamepad` 虚拟 Xbox 手柄。
- 默认要求 Forza 在前台；如不在前台，V4 会停止而不是偷偷 fake-focus。

## 启动

先确保 V3 模型和 OCR 依赖可用：

```powershell
python v4_launcher.py --title Forza --skip-buy --skip-farm --allow-background
```

上面的命令用于从当前页面试跑 V4 导航，不跑买车和刷分。真正完整模式三：

```powershell
python v4_launcher.py --title Forza
```

常用参数：

- `--skip-buy`：从当前页面续接 EventLab 导航。
- `--skip-farm`：只跑到 EventLab 开始赛事菜单，不启动刷分。
- `--farm-seconds 600`：把刷分阶段改为指定秒数，用于短验证。
- `--farm-seconds 0`：刷图阶段不设目标时长，会一直跑到手动停止或视觉刷图器自身看门狗停止。
- `--loop-rounds 3`：完整模式三外层循环 3 轮；每轮都会买车/加点、进 EventLab、刷图、收尾。
- `--loop-rounds 0`：完整模式三外层一直循环，直到手动停止或某轮失败。注意这和 `--farm-seconds 0` 不同，后者是单轮刷图无限跑。
- `--watchdog-seconds 120`：导航阶段 120 秒没有语义进展就触发恢复。
- `--auto-focus`：只做普通前台切换，不启用 KeepActive/fake-focus。默认关闭。
- `--allow-background`：跳过前台检查，主要用于只识别/调试，不推荐正式跑。

## V4 的安全策略

每次只执行一个按键，然后重新截图识别。动作建议必须带验证条件。

关键硬门槛：

- EventLab 赛事页：Y 只代表收藏/取消当前赛事，不会被当成进入“我的收藏”分页。切分页只用 LB/RB，并验证顶栏 active_tab。
- EventLab 收藏赛事：只有选中标题包含 `SP Farm / 24 second race = 10 skillpoints` 才允许 A。
- 车辆筛选：只有识别到 `收藏=未勾选` 才按 A；如果已经勾选，直接 B 返回，避免再次按 A 取消。
- EventLab 我的车辆：只有选中车识别为 `IMPREZA 22B-STI VERSION` 才允许 A。
- 赛事暂停锁态：带锁创意中心/车辆页面不当作普通可进入菜单；默认 `B` 返回当前比赛。如果目标是退出比赛，应先切到剧情页确认“返回比赛/退出比赛”文字，不从锁住卡片继续进入。
- 弹窗：未知弹窗不盲按 A，必须确认文字/按钮语义。

## 120 秒卡顿处理

V4 导航阶段会记录语义进展 token：页面、分页、选中项、筛选勾选状态、滚动状态等。超过 120 秒没有变化时：

1. 保存截图和 JSON 到 `reports/v4_attention_*.png/json`。
2. 对明确安全的页面做有限恢复，例如控制器弹窗按 A、自由漫游按 Menu、待机页按 A/B/Menu 逐个探测。
3. 恢复次数用尽或页面语义不安全时停止，写 `reports/v4_attention_latest.json` 等待接手。

## 打包

```powershell
build_v4.bat
```

输出：

- `dist\Forza6HelperV4.exe`
- `dist\README_V4.txt`

## 当前限制

- 买车和刷分内循环仍复用 V1 的 `BuyCarRunner` / `SmartRunner`，V4 重点接管最容易错的 EventLab 导航、收藏筛选和 22B 选择。
- 如果目标 EventLab 赛事没有出现在“我的收藏”，V4 会停止，不会进入非目标赛事。
- 如果收藏筛选后 22B 没出现，V4 会停止，不会选择非 22B。
