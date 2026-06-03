> ⚠️ **已淘汰，别用。** 本版已被 `Forza6HelperV4GUI.exe` 取代，仅作历史留存。请看根目录 [`README.md`](README.md)。

# Forza6Helper V2 页面理解测试版

V2 是单独的实验程序，不替换当前稳定版助手。它只做三件事：

1. 截取 Forza 窗口画面。
2. 使用 OCR 和布局关系理解当前页面。
3. 显示“如果要去某个目标，下一步应该按什么，以及按完后要验证什么”。

V2 不连接虚拟手柄，也不会发送任何按键。

更新：V3/Vision 已在独立路径继续推进，包含样本采集、焦点进入采样、EventLab/比赛页采样、YOLO 数据集、ONNX 推理、混合识别、benchmark 和打包入口。V2 仍保留为轻量页面语义层和回归测试基线，详见 `README_VISION.md`。

## 启动

开发环境：

```bat
.venv\Scripts\pythonw.exe v2_launcher.py
```

打包：

```bat
build_v2.bat
```

输出：

```text
dist\Forza6HelperV2.exe
```

## 当前定位

V2 是“页面理解测试版”，不是正式挂机版。它的价值是先把识别层做稳，再决定是否接回 V1 的 runner。

当前测试重点：

- 暂停菜单剧情分页：识别当前分页和焦点 tile。
- 暂停菜单车辆分页：识别当前分页和焦点 tile。
- 不同窗口大小下的焦点框检测。
- 每一步动作建议都必须带验证条件，避免盲按。

## 识别目标

当前 V2 会输出：

- 页面类型，例如 `pause_story`、`pause_vehicle`、`pause_creative_hub`、`eventlab_events`、`race_menu`、`race_hud`、`race_result`。
- 深层页面，例如 `vehicle_mastery` 车辆熟练度技能树、`eventlab_my_cars` 车辆列表、`post_race_next` 赛后下一站、`tuning_menu` 调校页、`online_player_list` 在线玩家列表。
- 当前顶部分页，例如 `剧情`、`车辆`、`创意中心`。
- 当前焦点，例如 `收集簿`、`世界地图`、`车辆熟练度`、`礼物掉落箱`。
- OCR 分区：顶部、中部、底部，避免把底部提示栏误当成页面正文。
- 动作建议，例如从 `剧情` 去 `车辆` 应该按 `RB`，并要求按后重新识别确认。

## 已有校准样本

当前测试覆盖过这些暂停菜单焦点：

- 剧情分页：`收集簿`、`世界地图`、`下一站`、`设置`、`退出游戏`、`Festival Playlist / 欢迎来到日本`。
- 车辆分页：`购买新车与二手车`、`更换车辆`、`车辆熟练度`、`秘藏座驾`、`车房宝物`、`礼物掉落箱`、`汽车喇叭`、`调校车辆`。

运行回放测试：

```bat
py -m pytest -q tests\test_v2_semantic.py
```

也可以固定使用 `.venv` 跑测试：

```bat
.venv\Scripts\python.exe -m pytest -q tests\test_v2_semantic.py tests\test_v3_vision.py
```

## 为什么单独做

当前稳定版已经能跑主流程。V2 用来验证更稳的“页面语义层”，避免直接改稳定版状态机。

## YOLO 方向

YOLO 可以作为下一阶段候选，但建议做成混合方案：

- YOLO 检测页面结构、焦点框、弹窗、关键卡片。
- OCR 只读取必要文本，例如 `22B`、`我的收藏`、共享代码和确认弹窗。
- 状态机按“模型输出 + 验证条件”行动，按完必须重新识别。

只有当 YOLO/ONNX 小模型在速度和准确率上都赢过当前 OCR/规则方案时，才考虑接入正式版。

## V3 / Vision 实验链路

新的“最强识别版”已放在独立 `v3/` 路径，不改 V1 稳定 runner。入口是：

```bat
.venv\Scripts\pythonw.exe vision_launcher.py
```

详细说明见 `README_VISION.md`。当前 V3 已包含样本采集、自动候选框、YOLO 数据集生成、Ultralytics 训练入口、ONNXRuntime 推理、混合识别、benchmark 和 `Forza6HelperVision.exe` 打包入口。首批本地样本只覆盖车辆分页焦点，因此 YOLO 模型仍是实验能力，不应接入正式 runner。
