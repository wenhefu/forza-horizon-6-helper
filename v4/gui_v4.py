"""Tk GUI for the V4 vision-guided mode-three runner.

Like the V1 GUI, but it drives V4Mode3Runner (V3 vision recognition + V1 buy/
farm subrunners). Run it yourself so Forza stays foreground -- that avoids the
background-launch focus problem. It only sends normal virtual Xbox controller
input via ViGEmBus.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import config
import focus
import window_util
from driver_check import check_vigembus, open_vigembus_download

# Cohesive dark "Fluent"-style palette: one unified window background (the title bar is darkened
# via DWM too), subtly-elevated cards, a single green accent + a muted danger for stop actions.
COLORS = {
    "bg": "#181e1b",         # unified window background (header + shell + behind cards)
    "bg_deep": "#212a25",    # subtle inset panel (tip strip)
    "surface": "#222a26",    # cards
    "surface2": "#2b332e",   # inputs / inner controls
    "border": "#333d37",     # hairline card border
    "text": "#e8f0ec",       # primary text
    "muted": "#8ea29a",      # secondary text
    "accent": "#27a47b",     # primary action
    "accent_hi": "#2fbe8f",  # primary hover
    "accent_lo": "#20805f",  # primary pressed / disabled
    "danger": "#b9554e",     # stop / destructive
    "danger_hi": "#cb645c",
    "lime": "#b8ff2c",       # Forza highlight
    "log_bg": "#11140f",
    "log_text": "#cfe0d7",
}
FONT = ("Microsoft YaHei UI", 13)
FONT_TITLE = ("Microsoft YaHei UI", 24, "bold")
FONT_SECTION = ("Microsoft YaHei UI", 15, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 11)
FONT_MONO = ("Cascadia Mono", 12)
REPORT_PATH = Path("reports/v4_mode3_latest.json")


class V4App:
    def __init__(self, root):
        self.root = root
        root.title("地平线6 · 自动助手")
        root.configure(bg=COLORS["bg"])
        root.resizable(True, True)
        root.minsize(1040, 780)
        root.geometry("1180x840")
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._configure_styles()
        self.log_q: queue.Queue = queue.Queue()
        self._flog = self._setup_file_log()   # persist every GUI log line to logs/gui.log
        self.runner = None
        self.runner_ready = False

        # options
        self.farm_minutes = tk.StringVar(value="30")
        self.loop_rounds = tk.StringVar(value="0")
        self.max_failures = tk.StringVar(value="3")
        self.watchdog_secs = tk.StringVar(value="180")
        self.startup_delay = tk.StringVar(value="4")
        self.skip_buy = tk.BooleanVar(value=False)
        self.skip_farm = tk.BooleanVar(value=False)
        self.exit_after_farm = tk.BooleanVar(value=True)
        self.auto_focus = tk.BooleanVar(value=True)
        self.farm_mode = tk.StringVar(value="vision")
        # 循环顺序：buy_first=先买车再跑图(默认)；farm_first=先跑图再买车。都从暂停菜单起步。
        self.loop_order = tk.StringVar(value="buy_first")
        # Navigation is the one proven full-path nav (no V4/V5 toggle exposed -- one version).
        # sell-duplicates (Phase B): clear junk 22B copies, keep the favorited farm car
        self.sell_max = tk.StringVar(value="80")
        self.sell_model = tk.StringVar(value="22B")  # car-name substring to clear dups of
        self._sell_thread = None
        self._sell_stop = threading.Event()
        # auction snipe (Phase C): buy out the first listing of a search the USER pre-sets
        self.snipe_max = tk.StringVar(value="1")     # max cars to buy out per run
        # Experimental speed levers (OFF by default; need a live test before trusting -- the
        # validated path runs when these are off). 快速买断=Y quick-menu skips the detail page;
        # 变化才识别=skip OCR on unchanged frames in the watch loop.
        self.snipe_fast = tk.BooleanVar(value=False)
        self.snipe_roc = tk.BooleanVar(value=False)
        self._snipe_thread = None
        self._snipe_stop = threading.Event()
        # buy-all-unowned (autoshow 车展)
        self.unowned_max = tk.StringVar(value="5")   # max un-owned cars to buy per run
        self._unowned_thread = None
        self._unowned_stop = threading.Event()
        self.countdown_var = tk.StringVar(value="")  # prominent farm-round countdown
        self.win_target = tk.StringVar(value=window_util.DEFAULT_PRESET)
        self.driver_status = tk.StringVar(value="正在检查虚拟手柄驱动...")
        self.status_var = tk.StringVar(value="正在加载识别模型...")

        shell = tk.Frame(root, bg=COLORS["bg"], padx=18, pady=16)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)   # the content row grows with the window

        self._build_header(shell)         # row 0, full width

        # Landscape two-column body: controls on the LEFT, the log/report on the RIGHT.
        content = tk.Frame(shell, bg=COLORS["bg"])
        content.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        content.columnconfigure(0, weight=0, minsize=620)   # left controls (fixed-ish)
        content.columnconfigure(1, weight=1, minsize=420)   # right log grows
        content.rowconfigure(0, weight=1)

        left = tk.Frame(content, bg=COLORS["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.columnconfigure(0, weight=1)
        self._build_options(left)         # left row 0
        self._build_actions(left)         # left row 1

        self._build_log(content)          # right column, full height

        self.root.after(200, self._refresh_driver)
        self.root.after(300, self._init_runner_async)
        self.root.after(100, self._tick)
        self._enable_dark_titlebar()
        self.root.after(60, self._enable_dark_titlebar)  # re-apply once the window is mapped

    # -- UI -----------------------------------------------------------------
    def _enable_dark_titlebar(self):
        """Darken the native title bar (Win10 1809+/Win11) so the window chrome matches the dark
        app -- 'the top blends into the program background'. No-op off Windows / on failure."""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            val = ctypes.c_int(1)
            for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (20 = Win11, 19 = older Win10)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass

    def _configure_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=FONT, background=COLORS["surface"], foreground=COLORS["text"])
        # Secondary buttons (切回游戏 / 开始清理 / 开始抢车 / 开始买 ...)
        style.configure("App.TButton", padding=(20, 14), background=COLORS["surface2"],
                        foreground=COLORS["text"], borderwidth=0, focuscolor=COLORS["surface2"],
                        font=FONT, relief="flat")
        style.map("App.TButton",
                  background=[("active", "#3a463f"), ("disabled", "#242c28")],
                  foreground=[("disabled", COLORS["muted"])])
        # Primary action (开始)
        style.configure("Primary.TButton", padding=(22, 15), background=COLORS["accent"],
                        foreground="#ffffff", borderwidth=0, focuscolor=COLORS["accent"],
                        font=(FONT[0], FONT[1], "bold"), relief="flat")
        style.map("Primary.TButton",
                  background=[("active", COLORS["accent_hi"]), ("disabled", "#2a3530")],
                  foreground=[("disabled", COLORS["muted"])])
        # Stop / halt buttons
        style.configure("Stop.TButton", padding=(20, 14), background=COLORS["danger"],
                        foreground="#ffffff", borderwidth=0, focuscolor=COLORS["danger"],
                        font=FONT, relief="flat")
        style.map("Stop.TButton",
                  background=[("active", COLORS["danger_hi"]), ("disabled", "#39302f")],
                  foreground=[("disabled", COLORS["muted"])])
        style.configure("App.TCheckbutton", background=COLORS["surface"], foreground=COLORS["text"], font=FONT)
        style.map("App.TCheckbutton", background=[("active", COLORS["surface"])],
                  foreground=[("disabled", COLORS["muted"])])
        style.configure("App.TRadiobutton", background=COLORS["surface"], foreground=COLORS["text"], font=FONT)
        style.map("App.TRadiobutton", background=[("active", COLORS["surface"])])
        # Dark input fields (both the App.TEntry rows and the bare ttk.Entry/Combobox)
        for ent in ("App.TEntry", "TEntry"):
            style.configure(ent, padding=(10, 9), fieldbackground=COLORS["surface2"],
                            foreground=COLORS["text"], bordercolor=COLORS["border"],
                            insertcolor=COLORS["text"], borderwidth=1, relief="flat")
        style.configure("TCombobox", fieldbackground=COLORS["surface2"], background=COLORS["surface2"],
                        foreground=COLORS["text"], bordercolor=COLORS["border"], arrowcolor=COLORS["text"],
                        padding=(10, 8), borderwidth=1, relief="flat")
        style.map("TCombobox",
                  fieldbackground=[("readonly", COLORS["surface2"])],
                  foreground=[("readonly", COLORS["text"])],
                  selectbackground=[("readonly", COLORS["surface2"])])
        # Modern flat scrollbar: just a slim thumb, NO arrow buttons (clam draws boxy arrows).
        style.layout("Modern.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure("Modern.Vertical.TScrollbar", background=COLORS["surface2"],
                        troughcolor=COLORS["log_bg"], bordercolor=COLORS["log_bg"],
                        borderwidth=0, relief="flat", width=10, arrowsize=0)
        style.map("Modern.Vertical.TScrollbar", background=[("active", COLORS["border"])])

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
        head.grid(row=0, column=0, sticky="we", pady=(2, 10))
        head.columnconfigure(0, weight=1)
        tk.Label(head, text="地平线 6 · 自动助手", bg=COLORS["bg"], fg=COLORS["text"],
                 font=FONT_TITLE, anchor="w").grid(row=0, column=0, sticky="w")
        tk.Label(head, text="买车加点 · EventLab 刷图 · 拍卖抢车 · 清理重复 · 买未拥有",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=FONT_SMALL, anchor="w").grid(
                     row=1, column=0, sticky="w", pady=(3, 9))
        guide = tk.Frame(head, bg=COLORS["bg_deep"], padx=13, pady=9)
        guide.grid(row=2, column=0, sticky="we")
        guide.columnconfigure(0, weight=1)
        tk.Label(guide, text="点开始后让 Forza 保持前台,窗口模式最稳;只发虚拟手柄输入,不注入游戏。",
                 bg=COLORS["bg_deep"], fg=COLORS["lime"], font=FONT_SMALL, anchor="w").grid(row=0, column=0, sticky="w")
        tk.Label(guide, textvariable=self.driver_status, bg=COLORS["bg_deep"], fg=COLORS["muted"],
                 font=FONT_SMALL, anchor="w").grid(row=1, column=0, sticky="w", pady=(3, 0))
        # Prominent farm-round countdown box -- shown only while a farm round is running.
        self.countdown_box = tk.Label(head, textvariable=self.countdown_var, bg=COLORS["accent"],
                                      fg="#ffffff", font=(FONT[0], 17, "bold"), anchor="center",
                                      padx=16, pady=10)
        self.countdown_box.grid(row=3, column=0, sticky="we", pady=(10, 0))
        self.countdown_box.grid_remove()   # hidden until farming

    def _build_options(self, left):
        card = self._card(left, "运行选项")
        card.grid(row=0, column=0, sticky="new", pady=(0, 14))
        body = card.body
        body.columnconfigure(1, weight=1)
        self._field(body, 0, "跑图时间(分钟)", self.farm_minutes, "每轮刷图;0=一直跑")
        self._field(body, 1, "启动倒计时(秒)", self.startup_delay, "点开始后留时间切回游戏")
        # The rest (循环轮数=0 无限 / 连续失败上限 / 看门狗 / 跳过买车·刷图 / 回收尾 / 自动切回 /
        # 刷图引擎) stay at their sensible defaults and are no longer exposed -- cleaner UI.
        om = tk.Frame(body, bg=COLORS["surface"])
        om.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        tk.Label(om, text="循环顺序:", bg=COLORS["surface"], fg=COLORS["text"], font=FONT).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(om, text="先买车再跑图(默认)", variable=self.loop_order, value="buy_first",
                        style="App.TRadiobutton").grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Radiobutton(om, text="先跑图再买车", variable=self.loop_order, value="farm_first",
                        style="App.TRadiobutton").grid(row=0, column=2, sticky="w", padx=(8, 0))

    def _field(self, parent, row, label, var, unit):
        rowf = tk.Frame(parent, bg=COLORS["surface"])
        rowf.grid(row=row, column=0, columnspan=3, sticky="we", pady=7)
        tk.Label(rowf, text=label, bg=COLORS["surface"], fg=COLORS["text"], font=FONT,
                 width=13, anchor="w").pack(side="left")
        ttk.Entry(rowf, textvariable=var, width=7, style="App.TEntry").pack(side="left")
        tk.Label(rowf, text=unit, bg=COLORS["surface"], fg=COLORS["muted"], font=FONT_SMALL,
                 anchor="w").pack(side="left", padx=(14, 0))

    def _build_actions(self, left):
        card = self._card(left, "控制")
        card.grid(row=1, column=0, sticky="new")
        body = card.body
        for c in range(4):
            body.columnconfigure(c, weight=1, uniform="act")
        self.start_btn = ttk.Button(body, text="开始", command=self.on_start, style="Primary.TButton", state="disabled")
        self.start_btn.grid(row=0, column=0, sticky="we", padx=(0, 6))
        self.stop_btn = ttk.Button(body, text="停止", command=self.on_stop, style="Stop.TButton", state="disabled")
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
        # Sell-duplicates: clear junk copies of a model (keeps the favorited/driving car, verifies
        # the remove-confirm before each delete). Start from My Vehicles / the pause menu. No count
        # cap -- it sweeps all duplicates; 停止 halts.
        sellrow = tk.Frame(body, bg=COLORS["surface"])
        sellrow.grid(row=2, column=0, columnspan=4, sticky="we", pady=(12, 0))
        tk.Label(sellrow, text="清理重复车(留收藏/在驾驶的):", bg=COLORS["surface"], fg=COLORS["text"], font=FONT).pack(side="left")
        tk.Label(sellrow, text="车名含", bg=COLORS["surface"], fg=COLORS["muted"], font=FONT_SMALL).pack(side="left", padx=(10, 3))
        ttk.Entry(sellrow, textvariable=self.sell_model, width=10).pack(side="left")
        self.sell_btn = ttk.Button(sellrow, text="开始清理", command=self.on_clear_duplicates,
                                   style="App.TButton", state="disabled")
        self.sell_btn.pack(side="left", padx=(10, 6))
        self.sell_stop_btn = ttk.Button(sellrow, text="停止", command=self.on_sell_stop,
                                        style="Stop.TButton", state="disabled")
        self.sell_stop_btn.pack(side="left")
        # Auction-house snipe: the USER pre-sets a tight search and STOPS ON the 搜寻 page; it
        # re-searches each cycle and buys 买断 (never 竞价/bid) until stopped.
        sniperow = tk.Frame(body, bg=COLORS["surface"])
        sniperow.grid(row=3, column=0, columnspan=4, sticky="we", pady=(12, 0))
        tk.Label(sniperow, text="拍卖场抢车(停在『搜寻』页、过滤设紧):", bg=COLORS["surface"],
                 fg=COLORS["text"], font=FONT).pack(side="left")
        self.snipe_buy_btn = ttk.Button(sniperow, text="开始抢车", command=self.on_snipe_buy,
                                        style="App.TButton", state="disabled")
        self.snipe_buy_btn.pack(side="left", padx=(10, 6))
        self.snipe_stop_btn = ttk.Button(sniperow, text="停止", command=self.on_snipe_stop,
                                         style="Stop.TButton", state="disabled")
        self.snipe_stop_btn.pack(side="left")
        # Buy-all-unowned (autoshow 车展): apply the 未拥有 filter, then loop-buy EVERY un-owned car
        # (re-applying the filter each cycle -- it resets on re-entry) until the grid is empty or
        # stopped. The USER stops on the 车展 vehicle grid.
        unownedrow = tk.Frame(body, bg=COLORS["surface"])
        unownedrow.grid(row=4, column=0, columnspan=4, sticky="we", pady=(12, 0))
        tk.Label(unownedrow, text="买未拥有的车(停在『车展』网格页):", bg=COLORS["surface"],
                 fg=COLORS["text"], font=FONT).pack(side="left")
        self.unowned_buy_btn = ttk.Button(unownedrow, text="开始买", command=self.on_unowned_buy,
                                          style="App.TButton", state="disabled")
        self.unowned_buy_btn.pack(side="left", padx=(10, 6))
        self.unowned_stop_btn = ttk.Button(unownedrow, text="停止", command=self.on_unowned_stop,
                                           style="Stop.TButton", state="disabled")
        self.unowned_stop_btn.pack(side="left")
        tk.Label(body, textvariable=self.status_var, bg=COLORS["surface"], fg=COLORS["muted"],
                 font=FONT_SMALL, anchor="w").grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 0))

    def _build_log(self, content):
        card = self._card(content, "运行日志")
        card.grid(row=0, column=1, sticky="nsew")   # right column, full height
        card.body.rowconfigure(0, weight=1)
        card.body.columnconfigure(0, weight=1)
        self.log = tk.Text(card.body, width=44, height=10, state="disabled",
                           font=FONT_MONO, bg=COLORS["log_bg"], fg=COLORS["log_text"],
                           relief="flat", bd=0, padx=14, pady=12, wrap="word",
                           insertbackground=COLORS["log_text"], spacing1=1, spacing3=3,
                           selectbackground=COLORS["surface2"], selectforeground=COLORS["text"])
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(card.body, orient="vertical", command=self.log.yview,
                           style="Modern.Vertical.TScrollbar")
        sb.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.log.config(yscrollcommand=sb.set)

    # -- runner wiring ------------------------------------------------------
    def _setup_file_log(self):
        """Persist every GUI log line to logs/gui.log so runs (auction / un-owned / etc.) are
        diagnosable after the fact -- the on-screen panel is cleared each launch."""
        try:
            os.makedirs("logs", exist_ok=True)
            lg = logging.getLogger("forza6gui")
            lg.setLevel(logging.INFO)
            if not lg.handlers:
                h = logging.FileHandler(os.path.join("logs", "gui.log"), encoding="utf-8")
                h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
                lg.addHandler(h)
            lg.info("==== GUI session start ====")
            return lg
        except Exception:
            return None

    def _log(self, msg: str):
        self.log_q.put(str(msg))
        if self._flog is not None:
            try:
                self._flog.info(str(msg))
            except Exception:
                pass

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
        self.runner.nav_mode = "v4"   # one version: the proven full-path nav
        buy_first = self.loop_order.get() != "farm_first"
        order_label = "先买车再跑图" if buy_first else "先跑图再买车"
        self._log(
            f"开始:farm_mode={self.farm_mode.get()} 顺序={order_label} 跑图={farm_minutes}分钟 完整循环={loop_rounds}轮 "
            f"看门狗={watchdog:.0f}s 跳过买车={self.skip_buy.get()} 跳过刷图={self.skip_farm.get()}"
        )
        if not buy_first and self.skip_farm.get():
            self._log("注意: “先跑图再买车”需要刷图阶段；已勾选跳过刷图，本轮会退化成“只导航再买车”，买车可能不是从干净起点开始。")
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
            buy_first=buy_first,
        )

    def on_stop(self):
        if self.runner is not None:
            self.runner.stop()
        self._sell_stop.set()   # also stop a running duplicate-clear
        self._snipe_stop.set()  # ...and a running auction snipe
        self._unowned_stop.set()  # ...and a running buy-all-unowned
        self._log("已请求停止。")

    def _sell_busy(self) -> bool:
        return self._sell_thread is not None and self._sell_thread.is_alive()

    def on_sell_stop(self):
        self._sell_stop.set()
        self._log("清理重复车：已请求停止(当前这步走完就停)。")

    def on_clear_duplicates(self):
        if not self.runner_ready or self.runner is None:
            self._log("识别模型还在加载,请稍候。")
            return
        if self.runner.is_running() or self._sell_busy():
            return
        max_sell = 99999   # no cap: sweep ALL duplicates (favorited/driving car kept; 停止 halts)
        model = (self.sell_model.get() or "").strip() or "22B"
        self._sell_stop.clear()
        self._log(f"开始清理重复「{model}」：清理所有重复(留收藏/正在驾驶的那辆),删前核对确认框,可随时按停止。")
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
        max_cars = None   # no cap -- keep sniping until 停止
        self._snipe_stop.clear()
        # Clear, correct start-page guidance (the snipe RE-SEARCHES every cycle).
        self._log("【抢车怎么用】① 进 拍卖场 → 搜索拍卖；② 设好 车厂+型号+最高买断价(设紧,只让目标车出现)；")
        self._log("　 ③ 把光标放到『确认』上,停在这个『搜寻』配置页(不用自己按确认);④ 再点这里。")
        self._log("　 它会自动:确认→看结果→有目标就买断,没有就退回搜寻再搜,如此循环(结果页不会自己刷新)。")
        self._log("抢车：不限数量,只买断不出价(误入竞价框会停手);随时按『停止』。")

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
                               on_log=self._log, stop_event=self._snipe_stop,
                               fast_buyout=self.snipe_fast.get(),
                               recognize_on_change=self.snipe_roc.get())
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
                    stop_event=self._snipe_stop, auto_focus=self.auto_focus.get(),
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

    def _unowned_busy(self) -> bool:
        return self._unowned_thread is not None and self._unowned_thread.is_alive()

    def on_unowned_dry(self):
        self._start_unowned(dry_run=True)

    def on_unowned_buy(self):
        self._start_unowned(dry_run=False)

    def on_unowned_stop(self):
        self._unowned_stop.set()
        self._log("买未拥有：已请求停止(当前这步走完就停)。")

    def _start_unowned(self, *, dry_run: bool):
        if not self.runner_ready or self.runner is None:
            self._log("识别模型还在加载,请稍候。")
            return
        if (self.runner.is_running() or self._sell_busy() or self._snipe_busy() or self._unowned_busy()):
            return
        max_cars = None   # no cap -- buy EVERY un-owned car until the grid is empty or 停止
        self._unowned_stop.clear()
        self._log("【买未拥有怎么用】① 进 车辆→购买车与二手车→车展,停在车辆网格页(看得到一格格车);② 再点这里。")
        self._log("　 它会自动:按 Y 开筛选→勾上『未拥有』→返回→买下第一辆,如此循环(每轮重开筛选,因为筛选会重置)。")
        self._log("买未拥有：买下所有未拥有的车,会花真金白银,随时按『停止』。")

        def worker():
            import time as _t
            from gamepad import Gamepad
            from v4.unowned_buyer import GRID, UnownedBuyIO, UnownedBuyer

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
                io = UnownedBuyIO(self.runner.recognizer, pad, title=config.GAME_TITLE,
                                  on_log=self._log, stop_event=self._unowned_stop)
                # Guard: only act on the showroom vehicle grid, so a mis-click can't wander/buy
                # through unrelated menus.
                seen = None
                for _ in range(3):
                    seen = io.screen()
                    if seen == GRID:
                        break
                if seen != GRID:
                    self._log(f"当前不在『车展』车辆网格页(识别={seen})。请进 车辆→购买车与二手车→车展,停在网格页再点。")
                    return
                buyer = UnownedBuyer(
                    io, dry_run=dry_run, max_cars=max_cars, on_log=self._log,
                    stop_event=self._unowned_stop, auto_focus=self.auto_focus.get(),
                )
                result = buyer.run()
                self._log(f"买未拥有结束：{result}(已买 {buyer.bought} 辆)")
            except Exception as exc:
                self._log(f"买未拥有出错:{exc}")
            finally:
                try:
                    if pad is not None:
                        pad.neutral()
                except Exception:
                    pass
                self._log("买未拥有线程结束。")

        self._unowned_thread = threading.Thread(target=worker, name="v4-gui-unowned", daemon=True)
        self._unowned_thread.start()

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
                   or self._sell_busy() or self._snipe_busy() or self._unowned_busy())
        idle_ready = self.runner_ready and not running
        self.start_btn.config(state="normal" if idle_ready else "disabled")
        self.sell_btn.config(state="normal" if idle_ready else "disabled")
        self.sell_stop_btn.config(state="normal" if self._sell_busy() else "disabled")
        self.snipe_buy_btn.config(state="normal" if idle_ready else "disabled")
        self.snipe_stop_btn.config(state="normal" if self._snipe_busy() else "disabled")
        self.unowned_buy_btn.config(state="normal" if idle_ready else "disabled")
        self.unowned_stop_btn.config(state="normal" if self._unowned_busy() else "disabled")
        self.stop_btn.config(state="normal" if running else "disabled")
        if running:
            self.status_var.set("运行中...")
        elif self.runner_ready and self.status_var.get() == "运行中...":
            self.status_var.set("已停止")
        self._update_countdown()
        self.root.after(120, self._tick)

    def _update_countdown(self):
        # Prominent "本轮跑图剩余 MM:SS" box, visible only while a farm round is counting down.
        secs = getattr(self.runner, "farm_remaining_seconds", None) if self.runner else None
        if secs is None:
            self.countdown_box.grid_remove()
            return
        s = int(secs)
        self.countdown_var.set(f"⏱  本轮跑图剩余  {s // 60:02d}:{s % 60:02d}")
        self.countdown_box.config(bg=COLORS["danger"] if s <= 30 else COLORS["accent"])
        self.countdown_box.grid()

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
