> ⚠️ **已淘汰，别用。** 本版已被 `Forza6HelperV4GUI.exe` 取代，仅作历史留存。请看根目录 [`README.md`](README.md)。

# Forza6Helper Vision 最强识别版

Vision 是独立 V3 识别实验版，不替换 V1 稳定 runner。它的目标是把 Forza 页面理解层做成可采样、可训练、可导出 ONNX、可 benchmark、可打包的链路。

## 安全边界

- 不注入游戏进程。
- 不 hook。
- 不 fake-focus。
- 不修改游戏文件。
- Vision GUI 只截图、OCR、ONNX 推理、显示建议和保存样本。
- 自动采样工具只在用户明确允许后使用 ViGEmBus/vgamepad 发送普通虚拟 Xbox 手柄输入，并且每按一步都会重新识别验证。

## 启动

```bat
.venv\Scripts\pythonw.exe vision_launcher.py
```

GUI 支持：

- 识别一次
- 实时识别
- 保存训练样本
- 生成 YOLO 数据集
- 显示 ONNX/规则检测框
- 显示 OCR 小区域结果
- 显示动作建议和验证条件
- 复制结果

模型/打包自检：

```bat
.venv\Scripts\python.exe -m v3.runtime_selftest --output reports\vision_runtime_selftest_source.json
dist\Forza6HelperVision.exe --self-test --output reports\vision_runtime_selftest_packaged.json
```

`ok=true` 表示 ONNX 模型已成功解析并由 ONNX Runtime 加载。GUI 启动时也会先加载模型，避免只在识别结果里才发现 `model not found`。

本轮热修增强：

- 低置信度且无模型命中时，自动读取顶部通知、中心弹窗、左上标题、底部提示等小区域 OCR，再重新做 V2 语义判断。
- 弹窗的“是/否/嗯/不”当前焦点会优先从黄绿焦点框小区域 OCR 读取。
- `autoshow_buy_sell` 左侧菜单焦点会用黄绿焦点框 OCR 覆盖粗粒度页面名。
- 季节更替等系统通知会识别为 `notification_overlay`，动作建议为等待，不盲按。
- 无明显 UI 的车辆展示/待机画面会识别为 `idle_showcase`，动作建议给出 `A`、`B`、`Menu` 唤醒探针；每一步都必须重新截图验证 UI 是否出现。
- `v3/ui_names.py` 提供固定 UI 名称表，过滤 `HORIZON`、品牌名、`CR`、按钮提示等装饰/背景 OCR。例：`HORIZON | eventlab | BFGoodrich | ALUMICRAFT | CR | 创建并浏览赛事` 会输出 `eventlab`，`更换 | 车辆` 会输出 `更换车辆`。
- `rule-fallback` 整页兜底框不再用整页 OCR 抢 `selected_item`，避免把 `festival`、`HORIZON`、Steam 页面文字等背景内容误认为当前焦点。
- `v3/ui_tree.py` 提供运行时 UI 导航索引树，会输出 `UI节点`、`导航路径`、`分页域`、`本层选项`、`可进入子页`。例：`autoshow_buy_sell` 会显示为 `暂停菜单 > 暂停菜单 / 车辆 > 购买与出售`，其中 `剧情/购买与出售/车辆/角色` 属于 `购买与出售顶部分页`，不会再和暂停菜单顶层分页混在一起。
- 弹窗标题和按钮焦点分离显示：例如标题是 `移动至嘉年华`，当前按钮焦点应显示 `嗯` 或 `不`，动作建议仍保持“不按键/等待确认”。
- 买车链路新增 `vehicle_buy_grid` 和 `manufacturer_grid`：购买车辆网格会输出底部按钮提示（选择、返回、排序、筛选、购买车展车辆票券、前往制造商、切换详情、切换数据），制造商列表会输出当前焦点品牌和滚动状态。
- `v3/vehicle_grid_sampler.py` 可对购买车辆网格/制造商表格做安全采样。默认是虚拟手柄；如果当前游戏使用键盘提示，可用 `--input-mode keyboard --click-titlebar` 做前台真实键盘采样。
- EventLab 赛事列表会优先读选中卡片的赛事标题，不再把 `EventLab` logo 当成选中项。模式三目标赛事应识别为 `SP Farm / 24 second race = 10 skillpoints` 后才建议 `A`。
- EventLab 赛事列表里的 `Y 最爱的赛事 / Y 移除最爱` 只是切换当前赛事收藏状态，不是进入“我的收藏”分页。
- EventLab 赛事列表现在会把顶部分页导航作为关键状态：先识别黑底/黄绿下划线的 active tab，例如 `热门`、`最新最热`、`我的收藏`。如果当前 tab 不是 `我的收藏`，动作建议会先给一小步 `LB/RB` 并要求重新识别，不会盲按 `A` 或误用 `Y`。
- EventLab 选车页只有在焦点车辆明确是 `IMPREZA 22B-STI VERSION` 时才建议进入下一步。
- EventLab 车辆筛选弹窗会显示 `筛选状态: 焦点=收藏 收藏=已勾选/未勾选`。未勾选时建议只按一次 `A`，确认勾选后建议 `B` 返回；已勾选时禁止再按 `A`，避免取消收藏筛选。
- `收藏` 复选框不会再只靠“框内有白色像素”判断；现在会先定位复选框、排除空框边框，再看内部是否真的有对勾。
- 黄绿焦点框检测在没有 `cv2` 时也有纯 numpy fallback，方便朋友机器缺 OpenCV 时仍保留规则兜底能力。

## 样本采集

手动采样：

```bat
.venv\Scripts\python.exe -m v3.sample_collector --capture --title Forza
```

导入本地截图：

```bat
.venv\Scripts\python.exe -m v3.sample_collector --import "C:\Users\fu\Videos\Captures\*.png" --limit 8
```

每个 raw 样本写入：

- `image.png`
- 窗口标题、尺寸、采集时间、采集方式
- OCR 原始结果
- V2 页面理解结果
- 自动候选框
- `metadata.json`

默认目录：`datasets/forza_ui/raw/`

## 自动采样工具

暂停分页巡航采样：

```bat
.venv\Scripts\python.exe -m v3.auto_sampler --title Forza --max-steps 120 --settle 0.95 --hold 0.16
```

焦点进入采样：

```bat
.venv\Scripts\python.exe -m v3.focus_sweeper --title Forza --max-steps 240 --settle 0.8 --hold 0.14 --enter-focused --enter-limit 36
```

EventLab/比赛页采样：

```bat
.venv\Scripts\python.exe -m v3.race_sampler --title Forza --max-steps 380 --settle 0.9 --hold 0.16
.venv\Scripts\python.exe -m v3.race_sampler --title Forza --max-steps 520 --settle 0.9 --hold 0.16 --run-seconds 180
```

买车网格/制造商采样：

```bat
.venv\Scripts\python.exe -m v3.vehicle_grid_sampler --title Forza --max-steps 18 --settle 0.75
.venv\Scripts\python.exe -m v3.vehicle_grid_sampler --title Forza --input-mode keyboard --click-titlebar --max-steps 18 --settle 0.75
.venv\Scripts\python.exe -m v3.vehicle_grid_sampler --title Forza --input-mode keyboard --click-titlebar --no-open-manufacturer --sequence dpad_down,dpad_down,dpad_down
```

注意：采样器不会按 A 购买车辆。`A/Enter` 只允许在识别到“控制器未连接”提示时用于关闭该提示。

窗口尺寸复采：

```bat
.venv\Scripts\python.exe -m v3.window_sizer --title Forza --width 1700 --height 1000 --x 40 --y 40
```

刷新 raw metadata 里的理解结果和候选框：

```bat
.venv\Scripts\python.exe -m v3.relabel_raw_samples --raw-root datasets\forza_ui\raw
```

审计 OCR 小区域到官方 UI 名称的映射：

```bat
.venv\Scripts\python.exe -m v3.ui_name_audit --raw-root datasets\forza_ui\raw --output reports\ui_name_audit_latest.json
```

导出当前 UI 导航索引树：

```bat
.venv\Scripts\python.exe -m v3.ui_tree --output reports\ui_navigation_tree.md
```

当前审计摘要：

- raw samples: 871
- candidate rows: 724
- official name rows: 455
- fallback rows needing review: 127
- unresolved rows: 142，其中 `vehicle_mastery_focus` 空文本技能节点占 100；这类运行时会保留 V2 已知选中项，不用整页 OCR 猜。

## YOLO 数据集

```bat
.venv\Scripts\python.exe -m v3.dataset --raw-root datasets\forza_ui\raw --dataset-root datasets\forza_ui\yolo
```

当前数据集摘要：

- raw samples: 993
- YOLO images: 993（当前快照为 `--no-augment` 快速生成）
- labeled images: 775
- data yaml: `datasets/forza_ui/yolo/data.yaml`

增强版生成命令仍是：

```bat
.venv\Scripts\python.exe -m v3.dataset --raw-root datasets\forza_ui\raw --dataset-root datasets\forza_ui\yolo
```

样本较多时增强版会明显更慢；快速复测可先用：

```bat
.venv\Scripts\python.exe -m v3.dataset --no-augment
```

样本缺口审计：

```bat
.venv\Scripts\python.exe -m v3.dataset_audit --raw-root datasets\forza_ui\raw --dataset-root datasets\forza_ui\yolo --output-dir reports
```

GUI 里也有“审计样本缺口”按钮，会输出 `reports\dataset_audit_latest.md/json`。这个工具同时看 YOLO 标注类别和 raw 页面语义覆盖，避免只看 1GB+ 图片体积误判为“样本够了”。

当前审计重点缺口：

- `vehicle_buy_grid`: 2/100，购买车辆网格严重不足。
- `my_cars_card_focus`: 22/120，车辆卡片焦点不足，尤其 22B/非 22B/不同滚动位置。
- `eventlab_my_cars`: 14/100，EventLab 选车页不足。
- `eventlab_filter`: 0/60，收藏筛选空框/已勾选/焦点移动真实样本不足。
- `race_pause_menu`: 0/60，比赛中带锁暂停菜单不足。
- `race_result`: 5/80，`post_race_next`: 4/80，赛后链路不足。
- `color_select`、`design_card_focus`、`car_preview` 都低于 5 个有效标注，需要补购买流程和待机展示分支。

当前 16 类：

```text
pause_story_focus
pause_vehicle_focus
pause_creative_hub_focus
eventlab_card_focus
my_cars_card_focus
vehicle_mastery_focus
race_menu
race_result
post_race_next
modal_warning
pause_my_horizon_focus
pause_online_focus
pause_store_focus
design_card_focus
color_select
car_preview
```

## 训练与导出

安装训练依赖：

```bat
.venv\Scripts\python.exe -m pip install -r requirements_vision.txt
```

当前主模型来自较均衡的 e2 checkpoint，导出命令：

```bat
.venv\Scripts\python.exe -m v3.train_yolo --checkpoint runs\detect\v3\runs\forza_ui_yolo_race_512_e2\weights\best.pt --imgsz 512 --output v3\models\forza_ui_yolo.onnx
```

从当前数据集继续训练的入口：

```bat
.venv\Scripts\python.exe -m v3.train_yolo --data datasets\forza_ui\yolo\data.yaml --model yolov8n.pt --epochs 2 --imgsz 512 --batch 8 --device cpu --name forza_ui_yolo_race_512 --output v3\models\forza_ui_yolo.onnx
```

## Benchmark

最终复测命令：

```bat
.venv\Scripts\python.exe benchmarks\benchmark_v3_vision.py --model v3\models\forza_ui_yolo.onnx --scales 1.0,0.65,1.25 --with-ocr --ocr-max 2 --raw-root datasets\forza_ui\raw --output-dir reports
```

完整 OCR 基准报告：`reports/vision_benchmark_20260528-223830.md`

结果摘要：

- V2 semantic/rule mean: 70.25 ms
- YOLO ONNX mean: 56.64 ms
- Hybrid mean: 146.52 ms
- Full OCR+V2 subset mean: 1721.33 ms
- V2 focus accuracy: 1.000
- Hybrid focus accuracy: 1.000
- Raw V3 label cases: 2145
- Raw YOLO label recall: 0.971
- Raw Hybrid label recall: 1.000
- Raw YOLO mean: 41.62 ms
- Raw Hybrid mean: 80.19 ms

官方名称热修后的快速复测报告：`reports/vision_benchmark_20260529-000819.md`

- V2 semantic/rule mean: 69.54 ms
- YOLO ONNX mean: 58.31 ms
- Hybrid mean: 146.80 ms
- V2 focus accuracy: 1.000
- Hybrid focus accuracy: 1.000
- Raw V3 label cases: 600
- Raw YOLO label recall: 0.985
- Raw Hybrid label recall: 1.000
- Raw YOLO mean: 40.06 ms
- Raw Hybrid mean: 67.43 ms

买车/制造商链路热修后的快速复测报告：`reports/vision_benchmark_20260529-023910.md`

- V2 semantic/rule mean: 58.32 ms
- YOLO ONNX mean: 52.36 ms
- Hybrid mean: 127.68 ms
- V2 focus accuracy: 1.000
- Hybrid focus accuracy: 1.000
- Raw V3 label cases: 160
- Raw YOLO label recall: 0.963
- Raw Hybrid label recall: 1.000
- Raw YOLO mean: 34.70 ms
- Raw Hybrid mean: 48.57 ms

EventLab 顶栏导航热修后的快速复测报告：`reports/vision_benchmark_20260529-065319.md`

- Raw V3 label cases: 80
- Raw YOLO label recall: 0.963
- Raw Hybrid label recall: 1.000
- Raw YOLO mean: 40.69 ms
- Raw Hybrid mean: 59.57 ms
- Source self-test: `reports/vision_runtime_selftest_nav_tabs_source.json`
- Packaged self-test: `reports/vision_runtime_selftest_packaged_nav_tabs.json`

弱点：

- `race_result` 真实 raw 只有 5 张，纯 YOLO per-label recall 为 0.600；混合层可由规则/OCR 补到 1.000。
- `pause_creative_hub_focus` 和 `pause_my_horizon_focus` 样本仍少，纯 YOLO 容易和相邻分页混淆。
- 因此当前仍建议保留在 V3/Vision 实验路径，不直接接入 V1 正式 runner。

## 打包

```bat
build_vision.bat
```

输出：

```text
dist\Forza6HelperVision.exe
```

打包包含：

- `v3/models/classes.txt`
- `v3/models/bootstrap_empty.onnx`
- `v3/models/forza_ui_yolo.onnx`
- `README_VISION.md`

## 朋友使用要求

- 推荐 Forza 使用窗口化或无边框窗口。
- 游戏窗口需要可见；被其它窗口遮挡时 BitBlt 截图可能读到遮挡内容。
- Vision GUI 本身不发送输入，不需要 ViGEmBus。
- 自动采样或未来接入正式 runner 时，朋友电脑仍需要 ViGEmBus + vgamepad。
- 当前模型已能独立识别和 benchmark，但样本分布还不够平衡，不建议直接替换 V1 主流程。
