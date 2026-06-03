"""Tk GUI for the V4 vision-guided mode-three runner.

Like the V1 GUI, but it drives V4Mode3Runner (V3 vision recognition + V1 buy/
farm subrunners). Run it yourself so Forza stays foreground -- that avoids the
background-launch focus problem. It only sends normal virtual Xbox controller
input via ViGEmBus.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext, ttk

import config
import focus
import window_util
from driver_check import check_vigembus, open_vigembus_download

COLORS = {
    "bg": "#0f463f",
    "bg_deep": "#0a302c",
    "surface": "#f7faf7",
    "border": "#d5e0d8",
    "text": "#16211e",
    "muted": "#60716a",
    "accent": "#116b5b",
    "lime": "#b8ff2c",
    "log_bg": "#071f1c",
    "log_text": "#d8e8df",
}
FONT = ("Microsoft YaHei UI", 11)
FONT_TITLE = ("Microsoft YaHei UI", 19, "bold")
FONT_SECTION = ("Microsoft YaHei UI", 13, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_MONO = ("Consolas", 11)
REPORT_PATH = Path("reports/v4_mode3_latest.json")


class V4App:
    def __init__(self, root):
        self.root = root
        root.title("地平线6 V4 视觉制导模式三")
        root.configure(bg=COLORS["bg"])
        root.resizable(True, True)
        root.minsize(520, 560)
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._configure_styles()
        self.log_q: queue.Queue = queue.Queue()
        self.runner = None
        self.runner_ready = False

        # options
        self.farm_minutes = tk.StringVar(value="3")
        self.loop_rounds = tk.StringVar(value="0")
        self.max_failures = tk.StringVar(value="3")
        self.watchdog_secs = tk.StringVar(value="180")
        self.startup_delay = tk.StringVar(value="4")
        self.skip_buy = tk.BooleanVar(value=False)
        self.skip_farm = tk.BooleanVar(value=False)
        self.exit_after_farm = tk.BooleanVar(value=True)
        self.auto_focus = tk.BooleanVar(value=True)
        self.farm_mode = tk.StringVar(value="vision")
        self.use_v5_nav = tk.BooleanVar(value=True)   # V5 event-driven nav is now the default
        # sell-duplicates (Phase B): clear junk 22B copies, keep the favorited farm car
        self.sell_max = tk.StringVar(value="80")
        self.sell_model = tk.StringVar(value="22B")  # car-name substring to clear dups of
        self._sell_thread = None
        self._sell_stop = threading.Event()
        # auction snipe (Phase C): buy out the first listing of a search the USER pre-sets
        self.snipe_max = tk.StringVar(value="1")     # max cars to buy out per run
        self._snipe_thread = None
        self._snipe_stop = threading.Event()
        self.win_target = tk.StringVar(value=window_util.DEFAULT_PRESET)
        self.driver_status = tk.StringVar(value="正在检查虚拟手柄驱动...")
        self.status_var = tk.StringVar(value="正在加载识别模型...")

        shell = tk.Frame(root, bg=COLORS["bg"], padx=14, pady=12)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)  # 运行日志这一行随窗口拉伸放大

        self._build_header(shell)
        self._build_options(shell)
        self._build_actions(shell)
        self._build_log(shell)

        self.root.after(200, self._refresh_driver)
        self.root.after(300, self._init_runner_async)
        self.root.after(100, self._tick)

    # -- UI -----------------------------------------------------------------
    def _configure_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=FONT)
        style.configure("App.TButton", padding=(16, 12), background="#e3efe7",
                        foreground=COLORS["text"], borderwidth=0, font=FONT)
        style.map("App.TButton", background=[("active", "#d2e6d9"), ("disabled", "#eef3ef")])
        style.configure("Primary.TButton", padding=(18, 13), background=COLORS["accent"],
                        foreground="#ffffff", borderwidth=0, font=(FONT[0], FONT[1], "bold"))
        style.map("Primary.TButton", background=[("active", "#0d5b4d"), ("disabled", "#94aaa2")])
        style.configure("App.TCheckbutton", background=COLORS["surface"], foreground=COLORS["text"], font=FONT)
        style.map("App.TCheckbutton", background=[("active", COLORS["surface"])])
        style.configure("App.TRadiobutton", background=COLORS["surface"], foreground=COLORS["text"], font=FONT)
        style.map("App.TRadiobutton", background=[("active", COLORS["surface"])])
        style.configure("App.TEntry", padding=(8, 7))

    def _card(self, parent, title):
        outer = tk.Frame(parent, bg=COLORS["surface"], padx=18, pady=15,
                         highlightbackground=COLORS["border"], highlightthickness=1)
        tk.Label(outer, text=title, bg=COLORS["surface"], fg=COLORS["text"],
                 font=FONT_SECTION, anchor="w").grid(row=0, column=0, sticky="we")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)
        body = tk.Frame(outer, bg=COLORS["surface"])
        body.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        body.columnconfigure(0, weight=1)
        outer.body = body
        return outer

    def _build_header(self, shell):
        head = tk.Frame(shell, bg=COLORS["bg"])
        head.grid(row=0, column=0, sticky="we", pady=(0, 8))
        tk.Label(head, text="V4 视觉制导 · 模式三", bg=COLORS["bg"], fg="#f5fff9",
                 font=FONT_TITLE, anchor="w").grid(row=0, column=0, sticky="w")
        tk.Label(head, text="买车加点 + EventLab 导航 + 视觉刷图(YOLO/规则识别) + 看门狗",
                 bg=COLORS["bg"], fg="#c7ddd4", font=FONT, anchor="w").grid(row=1, column=0, sticky="w", pady=(2, 6))
        guide = tk.Frame(head, bg=COLORS["bg_deep"], padx=12, pady=8)
        guide.grid(row=2, column=0, sticky="we")
        tk.Label(guide, text="自己开 GUI 跑:点开始后保持 Forza 在前台、别切窗口。窗口模式最稳。",
                 bg=COLORS["bg_deep"], fg=COLORS["lime"], font=FONT_SMALL, anchor="w").grid(row=0, column=0, sticky="w")
        tk.Label(guide, textvariable=self.driver_status, bg=COLORS["bg_deep"], fg="#d8e8df",
                 font=FONT_SMALL, anchor="w").grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_options(self, shell):
        card = self._card(shell, "运行选项")
        card.grid(row=1, column=0, sticky="we", pady=(0, 8))
        body = card.body
        body.columnconfigure(1, weight=1)
        self._field(body, 0, "跑图时间(分钟)", self.farm_minutes, "每轮刷图;0=一直跑")
        self._field(body, 1, "完整循环轮数", self.loop_rounds, "1=一轮;0=无限循环(自动开回收尾)")
        self._field(body, 2, "连续失败上限", self.max_failures, "循环时连续失败超过此次数才停")
        self._field(body, 3, "看门狗(秒)", self.watchdog_secs, "某阶段卡死超过此秒数自动停")
        self._field(body, 4, "启动倒计时(秒)", self.startup_delay, "点开始后留时间切回游戏")
        row = 5
        for text, var in [
            ("跳过买车阶段(从当前页直接导航去刷图)", self.skip_buy),
            ("跳过刷图阶段(只到开始赛事菜单)", self.skip_farm),
            ("刷图结束后回收尾到暂停菜单", self.exit_after_farm),
            ("自动切回游戏前台(失焦时尝试)", self.auto_focus),
            ("导航用 V5 事件驱动(默认·更快;买车/刷图仍用稳定版,取消则回退旧版导航)", self.use_v5_nav),
        ]:
            ttk.Checkbutton(body, text=text, variable=var, style="App.TCheckbutton").grid(
                row=row, column=0, columnspan=3, sticky="w", pady=5)
            row += 1
        fm = tk.Frame(body, bg=COLORS["surface"])
        fm.grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 0))
        tk.Label(fm, text="刷图引擎:", bg=COLORS["surface"], fg=COLORS["text"], font=FONT).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(fm, text="视觉制导(推荐)", variable=self.farm_mode, value="vision",
                        style="App.TRadiobutton").grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Radiobutton(fm, text="V1 SmartRunner(兜底)", variable=self.farm_mode, value="smart",
                        style="App.TRadiobutton").grid(row=0, column=2, sticky="w", padx=(8, 0))

    def _field(self, parent, row, label, var, unit):
        rowf = tk.Frame(parent, bg=COLORS["surface"])
        rowf.grid(row=row, column=0, columnspan=3, sticky="we", pady=7)
        tk.Label(rowf, text=label, bg=COLORS["surface"], fg=COLORS["text"], font=FONT,
                 width=13, anchor="w").pack(side="left")
        ttk.Entry(rowf, textvariable=var, width=7, style="App.TEntry").pack(side="left")
        tk.Label(rowf, text=unit, bg=COLORS["surface"], fg=COLORS["muted"], font=FONT_SMALL,
                 anchor="w").pack(side="left", padx=(14, 0))

    def _build_actions(self, shell):
        card = self._card(shell, "控制")
        card.grid(row=2, column=0, sticky="we", pady=(0, 8))
        body = card.body
        for c in range(4):
            body.columnconfigure(c, weight=1, uniform="act")
        self.start_btn = ttk.Button(body, text="开始", command=self.on_start, style="Primary.TButton", state="disabled")
        self.start_btn.grid(row=0, column=0, sticky="we", padx=(0, 6))
        self.stop_btn = ttk.Button(body, text="停止", command=self.on_stop, style="App.TButton", state="disabled")
        self.stop_btn.grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(body, text="切回游戏", command=self.activate_game, style="App.TButton").grid(row=0, column=2, sticky="we", padx=6)
        ttk.Button(body, text="打开报告", command=self.open_report, style="App.TButton").grid(row=0, column=3, sticky="we", padx=(6, 0))
        # Normalize the game window to 16:9 so the fixed-fraction detection works the
        # same on any monitor (incl. ultrawide 带鱼屏). External resize only -- no
        # injection/hook/focus-steal; needs the game in windowed/borderless mode.
        winrow = tk.Frame(body, bg=COLORS["surface"])
        winrow.grid(row=1, column=0, columnspan=4, sticky="we", pady=(8, 0))
        tk.Label(winrow, text="地平线窗口:", bg=COLORS["surface"], fg=COLORS["text"], font=FONT).pack(side="left")
        ttk.Combobox(winrow, textvariable=self.win_target, values=list(window_util.PRESETS_16_9.keys()),
                     width=10, state="readonly").pack(side="left", padx=(8, 8))
        ttk.Button(winrow, text="把地平线调成 16:9", command=self.resize_game_window,
                   style="App.TButton").pack(side="left")
        # Sell-duplicates: clear junk 22B copies (keeps the favorited/driving farm car,
        # verifies the remove-confirm dialog before each deletion). Start from My Vehicles
        # or the pause menu; it navigates the rest.
        sellrow = tk.Frame(body, bg=COLORS["surface"])
        sellrow.grid(row=2, column=0, columnspan=4, sticky="we", pady=(8, 0))
        tk.Label(sellrow, text="清理重复车(留收藏/在驾驶的):", bg=COLORS["surface"], fg=COLORS["text"], font=FONT).pack(side="left")
        tk.Label(sellrow, text="车名含", bg=COLORS["surface"], fg=COLORS["text"], font=FONT_SMALL).pack(side="left", padx=(8, 2))
        ttk.Entry(sellrow, textvariable=self.sell_model, width=10).pack(side="left")
        tk.Label(sellrow, text="最多", bg=COLORS["surface"], fg=COLORS["text"], font=FONT_SMALL).pack(side="left", padx=(8, 2))
        ttk.Entry(sellrow, textvariable=self.sell_max, width=5).pack(side="left")
        tk.Label(sellrow, text="辆", bg=COLORS["surface"], fg=COLORS["text"], font=FONT_SMALL).pack(side="left", padx=(2, 8))
        self.sell_btn = ttk.Button(sellrow, text="开始清理", command=self.on_clear_duplicates,
                                   style="App.TButton", state="disabled")
        self.sell_btn.pack(side="left")
        # Auction-house snipe (Phase C). The USER sets the search filter in-game and STOPS ON
        # THE 搜寻 (search-config) page; the snipe RE-SEARCHES each cycle (确认 -> read results
        # -> buy 买断 if the target is there, else back to 搜寻 and search again), because the
        # results list never auto-refreshes. "空跑验证" rehearses with zero spend; "开始抢车"
        # buys 买断 (never 竞价/bid); "停止抢车" (or the global 停止) halts it.
        sniperow = tk.Frame(body, bg=COLORS["surface"])
        sniperow.grid(row=3, column=0, columnspan=4, sticky="we", pady=(8, 0))
        tk.Label(sniperow, text="拍卖场抢车(停在『搜寻』页、过滤设紧):", bg=COLORS["surface"],
                 fg=COLORS["text"], font=FONT).pack(side="left")
        tk.Label(sniperow, text="最多", bg=COLORS["surface"], fg=COLORS["text"], font=FONT_SMALL).pack(side="left", padx=(8, 2))
        ttk.Entry(sniperow, textvariable=self.snipe_max, width=4).pack(side="left")
        tk.Label(sniperow, text="辆", bg=COLORS["surface"], fg=COLORS["text"], font=FONT_SMALL).pack(side="left", padx=(2, 8))
        self.snipe_dry_btn = ttk.Button(sniperow, text="空跑验证", command=self.on_snipe_dry,
                                        style="App.TButton", state="disabled")
        self.snipe_dry_btn.pack(side="left", padx=(0, 6))
        self.snipe_buy_btn = ttk.Button(sniperow, text="开始抢车", command=self.on_snipe_buy,
                                        style="App.TButton", state="disabled")
        self.snipe_buy_btn.pack(side="left", padx=(0, 6))
        self.snipe_stop_btn = ttk.Button(sniperow, text="停止抢车", command=self.on_snipe_stop,
                                         style="App.TButton", state="disabled")
        self.snipe_stop_btn.pack(side="left")
        tk.Label(body, textvariable=self.status_var, bg=COLORS["surface"], fg=COLORS["muted"],
                 font=FONT_SMALL, anchor="w").grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _build_log(self, shell):
        card = self._card(shell, "运行日志")
        card.grid(row=3, column=0, sticky="nsew")
        card.body.rowconfigure(0, weight=1)
        self.log = scrolledtext.ScrolledText(card.body, width=74, height=12, state="disabled",
                                             font=FONT_MONO, bg=COLORS["log_bg"], fg=COLORS["log_text"],
                                             relief="flat", bd=0, padx=10, pady=8)
        self.log.grid(row=0, column=0, sticky="nsew")

    # -- runner wiring ------------------------------------------------------
    def _log(self, msg: str):
        self.log_q.put(str(msg))

    def _init_runner_async(self):
        def worker():
            try:
                from v4.mode3_runner import V4Mode3Runner
                runner = V4Mode3Runner(title=config.GAME_TITLE, watchdog_seconds=180.0, on_log=self._log)
                self.runner = runner
                self.runner_ready = True
                self._log("识别模型已就绪,可以开始。")
                self.status_var.set("就绪")
            except Exception as exc:
                self._log(f"加载识别模型失败:{exc}")
                self.status_var.set("模型加载失败,请看日志")
        threading.Thread(target=worker, name="v4-gui-init", daemon=True).start()

    def _read_float(self, var, default):
        try:
            return float(str(var.get()).strip())
        except (TypeError, ValueError):
            var.set(str(default))
            return float(default)

    def on_start(self):
        if not self.runner_ready or self.runner is None:
            self._log("识别模型还在加载,请稍候再开始。")
            return
        if self.runner.is_running():
            return
        farm_minutes = self._read_float(self.farm_minutes, 3.0)
        loop_rounds = int(self._read_float(self.loop_rounds, 1.0))
        max_fail = int(self._read_float(self.max_failures, 3.0))
        farm_seconds = farm_minutes * 60.0 if farm_minutes > 0 else 0.0
        watchdog = max(20.0, self._read_float(self.watchdog_secs, 180.0))
        startup = max(0.0, self._read_float(self.startup_delay, 4.0))
        self.runner.watchdog_seconds = watchdog
        self.runner._farm_mode = self.farm_mode.get()
        self.runner.nav_mode = "v5" if self.use_v5_nav.get() else "v4"
        self._log(
            f"开始:farm_mode={self.farm_mode.get()} 跑图={farm_minutes}分钟 完整循环={loop_rounds}轮 看门狗={watchdog:.0f}s "
            f"跳过买车={self.skip_buy.get()} 跳过刷图={self.skip_farm.get()}"
        )
        if loop_rounds != 1 and not self.exit_after_farm.get():
            self.exit_after_farm.set(True)
            self._log("注意: 完整循环需要刷图后收尾才能进入下一轮；已自动为你勾上“刷图结束后回收尾到暂停菜单”。")
        if loop_rounds != 1 and self.skip_buy.get():
            self._log("注意: 你启用了外层循环但勾选了跳过买车；循环不会重新买车/加点。")
        if loop_rounds != 1 and farm_minutes <= 0:
            self._log("注意: 跑图时间=0 会让单轮刷图一直跑；外层循环不会进入下一轮。")
        self._log(f"请在 {startup:.0f} 秒内把 Forza 切到前台并停在合适页面(买车从自由漫游/暂停起步)。")
        self.runner.start(
            startup_delay=startup,
            farm_seconds=farm_seconds,
            run_buy=not self.skip_buy.get(),
            run_farm=not self.skip_farm.get(),
            exit_after_farm=self.exit_after_farm.get(),
            auto_focus=self.auto_focus.get(),
            require_foreground=True,
            loop_rounds=loop_rounds,
            max_consecutive_failures=max_fail,
        )

    def on_stop(self):
        if self.runner is not None:
            self.runner.stop()
        self._sell_stop.set()   # also stop a running duplicate-clear
        self._snipe_stop.set()  # ...and a running auction snipe
        self._log("已请求停止。")

    def _sell_busy(self) -> bool:
        return self._sell_thread is not None and self._sell_thread.is_alive()

    def on_clear_duplicates(self):
        if not self.runner_ready or self.runner is None:
            self._log("识别模型还在加载,请稍候。")
            return
        if self.runner.is_running() or self._sell_busy():
            return
        try:
            max_sell = max(1, int(self._read_float(self.sell_max, 80.0)))
        except Exception:
            max_sell = 80
        model = (self.sell_model.get() or "").strip() or "22B"
        self._sell_stop.clear()
        self._log(f"开始清理重复「{model}」：最多删 {max_sell} 辆,跳过收藏/正在驾驶的那辆,删前核对确认框(可随时按停止)。")
        self._log("请先在游戏里打开「我的车辆」(暂停→车辆→更换车辆),或停在 车辆 标签页,再点开始清理。")

        def worker():
            import time as _t
            from gamepad import Gamepad
            from v4.sell_runner import SellDuplicatesRunner

            pad = None
            try:
                try:
                    focus.activate_window(title_substr=config.GAME_TITLE, on_log=self._log)
                except Exception:
                    pass
                _t.sleep(0.6)
                pad = Gamepad()
                _t.sleep(0.6)
                for _ in range(3):  # dismiss a controller-disconnected modal if present
                    snap = self.runner.recognizer.capture(full_ocr=True, region_ocr=True)
                    if getattr(snap.v3, "screen", "") != "controller_disconnected":
                        break
                    pad.tap("a", hold=0.12)
                    _t.sleep(1.0)
                SellDuplicatesRunner(
                    self.runner.recognizer, pad, dry_run=False, on_log=self._log,
                    stop_event=self._sell_stop,
                ).run_sell(max_sell=max_sell, target_name=model)
            except Exception as exc:
                self._log(f"清理重复车出错:{exc}")
            finally:
                try:
                    if pad is not None:
                        pad.neutral()
                except Exception:
                    pass
                self._log("清理重复车结束。")

        self._sell_thread = threading.Thread(target=worker, name="v4-gui-sell", daemon=True)
        self._sell_thread.start()

    def _snipe_busy(self) -> bool:
        return self._snipe_thread is not None and self._snipe_thread.is_alive()

    def on_snipe_dry(self):
        self._start_snipe(dry_run=True)

    def on_snipe_buy(self):
        self._start_snipe(dry_run=False)

    def on_snipe_stop(self):
        self._snipe_stop.set()
        self._log("抢车：已请求停止(当前这步走完就停)。")

    def _start_snipe(self, *, dry_run: bool):
        if not self.runner_ready or self.runner is None:
            self._log("识别模型还在加载,请稍候。")
            return
        if (self.runner.is_running() or self._sell_busy() or self._snipe_busy()):
            return
        try:
            max_cars = max(1, int(self._read_float(self.snipe_max, 1.0)))
        except Exception:
            max_cars = 1
        self._snipe_stop.clear()
        # Clear, correct start-page guidance (the snipe RE-SEARCHES every cycle).
        self._log("【抢车怎么用】① 进 拍卖场 → 搜索拍卖；② 设好 车厂+型号+最高买断价(设紧,只让目标车出现)；")
        self._log("　 ③ 把光标放到『确认』上,停在这个『搜寻』配置页(不用自己按确认);④ 再点这里。")
        self._log("　 它会自动:确认→看结果→有目标就买断,没有就退回搜寻再搜,如此循环(结果页不会自己刷新)。")
        if dry_run:
            self._log("抢车[空跑]：只走到看到『买断』就退出,绝不购买(零风险验证一遍流程)。")
        else:
            self._log(f"抢车[真买]：最多买 {max_cars} 辆,只买断不出价(误入竞价框会停手);随时按『停止抢车』。")

        def worker():
            import time as _t
            from gamepad import Gamepad
            from v4.auction_runner import AuctionIO, AuctionSniper

            pad = None
            try:
                try:
                    focus.activate_window(title_substr=config.GAME_TITLE, on_log=self._log)
                except Exception:
                    pass
                _t.sleep(0.6)
                pad = Gamepad()
                _t.sleep(0.6)
                for _ in range(3):  # dismiss a controller-disconnected modal if present
                    snap = self.runner.recognizer.capture(full_ocr=True, region_ocr=True)
                    if getattr(snap.v3, "screen", "") != "controller_disconnected":
                        break
                    pad.tap("a", hold=0.12)
                    _t.sleep(1.0)
                io = AuctionIO(self.runner.recognizer, pad, title=config.GAME_TITLE,
                               on_log=self._log, stop_event=self._snipe_stop)
                # Guard: only act when we're actually in the auction house, so a mis-click
                # can't send stray B-presses wandering through unrelated menus.
                auction_tags = {"results", "search", "detail", "buyout_confirm", "bid_confirm"}
                seen = None
                for _ in range(3):
                    seen = io.screen()
                    if seen in auction_tags:
                        break
                if seen not in auction_tags:
                    self._log(f"当前不在拍卖场界面(识别={seen})。请进 拍卖场→搜索拍卖→确认,停在结果页再点。")
                    return
                sniper = AuctionSniper(
                    io, dry_run=dry_run, max_cars=max_cars, on_log=self._log,
                    stop_event=self._snipe_stop,
                )
                result = sniper.run()
                self._log(f"抢车结束：{result}(已买 {sniper.bought} 辆,尝试 {sniper.searches} 次)")
            except Exception as exc:
                self._log(f"抢车出错:{exc}")
            finally:
                try:
                    if pad is not None:
                        pad.neutral()
                except Exception:
                    pass
                self._log("抢车线程结束。")

        self._snipe_thread = threading.Thread(target=worker, name="v4-gui-snipe", daemon=True)
        self._snipe_thread.start()

    def activate_game(self):
        try:
            focus.activate_window(title_substr=config.GAME_TITLE, on_log=self._log)
        except Exception as exc:
            self._log(f"切回游戏失败:{exc}")

    def open_report(self):
        try:
            if REPORT_PATH.exists():
                os.startfile(str(REPORT_PATH.resolve()))
            else:
                self._log("还没有报告文件(跑一轮后生成 reports/v4_mode3_latest.json)。")
        except Exception as exc:
            self._log(f"无法打开报告:{exc}")

    def resize_game_window(self):
        # Force the game window's render area to a 16:9 preset so the
        # fixed-fraction detection works the same on any monitor (esp. ultrawide).
        try:
            ok, msg = window_util.resize_to_16_9(
                title_substr=config.GAME_TITLE, preset=self.win_target.get()
            )
            self._log(("窗口已调整:" if ok else "窗口未调整:") + msg)
        except Exception as exc:
            self._log(f"调整地平线窗口出错:{exc}")

    def _refresh_driver(self):
        try:
            status = check_vigembus()
            self.driver_status.set("虚拟手柄驱动:" + status.message)
            if not status.ok:
                self._log(status.message + " 正在打开 ViGEmBus 安装页。")
                try:
                    open_vigembus_download()
                except Exception:
                    pass
        except Exception as exc:
            self.driver_status.set(f"驱动检查失败:{exc}")

    def _tick(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                self.log.config(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.config(state="disabled")
        except queue.Empty:
            pass
        running = (bool(self.runner and self.runner.is_running())
                   or self._sell_busy() or self._snipe_busy())
        idle_ready = self.runner_ready and not running
        self.start_btn.config(state="normal" if idle_ready else "disabled")
        self.sell_btn.config(state="normal" if idle_ready else "disabled")
        self.snipe_dry_btn.config(state="normal" if idle_ready else "disabled")
        self.snipe_buy_btn.config(state="normal" if idle_ready else "disabled")
        self.snipe_stop_btn.config(state="normal" if self._snipe_busy() else "disabled")
        self.stop_btn.config(state="normal" if running else "disabled")
        if running:
            self.status_var.set("运行中...")
        elif self.runner_ready and self.status_var.get() == "运行中...":
            self.status_var.set("已停止")
        self.root.after(120, self._tick)

    def on_close(self):
        try:
            if self.runner is not None:
                self.runner.stop()
            self._sell_stop.set()
            self._snipe_stop.set()
        except Exception:
            pass
        self.root.after(150, self.root.destroy)


def main():
    import multiprocessing

    multiprocessing.freeze_support()  # guard against spawn re-running the entry script
    try:
        from single_instance import SingleInstance

        instance = SingleInstance(name="Local\\Forza6HelperV4")
    except Exception:
        instance = None
    if instance is not None and not instance.acquired:
        return  # another V4 GUI is already open; do not open a second window
    root = tk.Tk()
    if instance is not None:
        root._single_instance = instance
    V4App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
