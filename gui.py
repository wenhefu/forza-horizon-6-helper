"""Tk GUI for the FH6 helper. Package to .exe with build.bat on Windows."""
import math
import os
import queue
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from PIL import Image, ImageTk

from app_controller import AppController
from app_logging import LOG_PATH, log_startup_diagnostics, setup_logging
import config
from driver_check import VIGEMBUS_INSTALL_URL, check_vigembus, open_vigembus_download
import focus
from hotkeys import GlobalHotkey
from modes import DEFAULT_MODE_ID, MODE_BUY_CAR, MODE_COMBO, MODE_SKILL_POINTS, debug_modes, get_mode, product_modes
from settings import RuntimeSettings
from single_instance import SingleInstance


COLORS = {
    "bg": "#0f463f",
    "bg_deep": "#0a302c",
    "surface": "#f7faf7",
    "surface_soft": "#edf5ef",
    "border": "#d5e0d8",
    "text": "#16211e",
    "muted": "#60716a",
    "accent": "#116b5b",
    "accent_hover": "#0d5b4d",
    "accent_soft": "#ddf4e5",
    "lime": "#b8ff2c",
    "danger": "#a23b3b",
    "log_bg": "#071f1c",
    "log_text": "#d8e8df",
}

FONT = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 16, "bold")
FONT_SECTION = ("Microsoft YaHei UI", 10, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 8)
FONT_MONO = ("Consolas", 9)
PROJECT_URL = "https://github.com/wenhefu/forza-horizon-6-helper"

PREP_STEPS = [
    {
        "number": "01",
        "title": "车辆准备",
        "image": "assets/prep/vehicle_22b.png",
        "text": (
            "请先把加满点数的 1998 Subaru Impreza 22B-STI 加入“车库 -> 我的车辆”的收藏，"
            "并把当前驾驶车辆设为这台车。模式二和模式三都会围绕这台 22B 运行。"
        ),
    },
    {
        "number": "02",
        "title": "EventLab 收藏",
        "image": "assets/prep/eventlab_favorite.png",
        "text": (
            "要刷技能点，请务必把刷分图放进“创意中心 -> 游玩赛事 -> 我的收藏”的第一个位置。"
            "当前推荐共享代码：890 169 683。"
        ),
        "badge": "890 169 683",
    },
    {
        "number": "03",
        "title": "起始页面",
        "image": "assets/prep/pause_home.png",
        "text": (
            "开始流程前，请务必停留在暂停菜单的首个分页，如图所示。"
            "上方分页应从“剧情 / 车辆 / 我的地平线 / 在线 / 创意中心 / 商店”这一排开始。"
        ),
    },
]


def resource_path(relative_path):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative_path


class App:
    def __init__(self, root):
        self.root = root
        root.title("地平线6 刷分助手")
        root.resizable(False, False)
        root.configure(bg=COLORS["bg"])
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._configure_styles()

        self.log_q = queue.Queue()
        self.command_q = queue.Queue()
        self.logger = setup_logging()
        log_startup_diagnostics(self.logger)

        self.controller = AppController(on_log=self._log, logger=self.logger)
        self.hotkey = GlobalHotkey(on_press=self._enqueue_toggle, on_log=self._log)

        self.startup_var = tk.StringVar(value=str(config.STARTUP_DELAY))
        self.drive_var = tk.StringVar(value=str(config.DRIVE_SECONDS))
        self.total_var = tk.StringVar(value=str(config.TOTAL_MINUTES))
        self.keep_var = tk.BooleanVar(value=False)
        self.auto_focus_var = tk.BooleanVar(value=True)
        self.no_activate_var = tk.BooleanVar(value=True)
        self.require_foreground_var = tk.BooleanVar(value=True)
        self.resume_var = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value=DEFAULT_MODE_ID)
        self.show_debug_var = tk.BooleanVar(value=False)
        self.hint_var = tk.StringVar()
        self.driver_status_var = tk.StringVar(value="正在检查虚拟手柄驱动...")
        self.driver_install_prompted = False

        self.image_refs = []
        self.full_image_refs = []

        shell = tk.Frame(root, bg=COLORS["bg"], padx=14, pady=14)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, minsize=820)
        shell.columnconfigure(1, minsize=470)

        self._build_header(shell).grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 8))

        left = tk.Frame(shell, bg=COLORS["bg"])
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, minsize=400)
        left.columnconfigure(1, minsize=400)

        mode_card = self._card(left, "运行模式", "普通用户只需要前三个模式")
        mode_card.grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8))
        for row, mode in enumerate(product_modes()):
            self._add_mode_button(mode_card.body, mode, row)

        debug_row = len(product_modes())
        ttk.Checkbutton(
            mode_card.body,
            text="显示高级/调试模式",
            variable=self.show_debug_var,
            command=self.refresh_debug_visibility,
            style="App.TCheckbutton",
        ).grid(row=debug_row, column=0, sticky="w", pady=(8, 0))

        self.debug_mode_frame = tk.Frame(mode_card.body, bg=COLORS["surface"])
        self.debug_mode_frame.grid(row=debug_row + 1, column=0, sticky="we", pady=(4, 0))
        for row, mode in enumerate(debug_modes()):
            self._add_mode_button(self.debug_mode_frame, mode, row)

        settings_card = self._card(left, "运行参数", "填写后无需保存，点开始时读取")
        settings_card.grid(row=0, column=1, sticky="nsew", padx=(7, 0), pady=(0, 8))
        self._build_settings(settings_card.body)

        actions_card = self._card(left, "控制", "推荐保持游戏前台后启动")
        actions_card.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 8))
        self._build_actions(actions_card.body)

        hint_card = self._card(left, "当前模式提示", None)
        hint_card.grid(row=2, column=0, columnspan=2, sticky="we", pady=(0, 8))
        tk.Label(
            hint_card.body,
            textvariable=self.hint_var,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=FONT,
            justify="left",
            anchor="w",
            wraplength=780,
        ).grid(row=0, column=0, sticky="we")

        self.debug_buttons_frame = self._card(left, "调试工具", "需要人工救场时再打开")
        self.debug_buttons_frame.grid(row=3, column=0, columnspan=2, sticky="we", pady=(0, 8))
        self._build_debug_buttons(self.debug_buttons_frame.body)

        self.advanced_frame = self._card(left, "高级选项", "切换模式会自动设置，也可以手动覆盖")
        self.advanced_frame.grid(row=4, column=0, columnspan=2, sticky="we", pady=(0, 8))
        self._build_advanced(self.advanced_frame.body)

        log_card = self._card(left, "运行日志", "详细过程会写入 logs/forza6helper.log")
        log_card.grid(row=5, column=0, columnspan=2, sticky="we")
        self.log = scrolledtext.ScrolledText(
            log_card.body,
            width=72,
            height=5,
            state="disabled",
            font=FONT_MONO,
            bg=COLORS["log_bg"],
            fg=COLORS["log_text"],
            insertbackground=COLORS["log_text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
        )
        self.log.grid(row=0, column=0, sticky="we")

        prep_card = self._card(shell, "开始前准备", "这三件事做好后再点开始")
        prep_card.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        self._build_prep(prep_card.body)

        self._log(f"日志文件：{LOG_PATH}")
        self.hotkey.start()
        self.refresh_debug_visibility()
        self.apply_mode()
        self.root.after(250, self.refresh_driver_status)
        self.root.after(500, self.connect_gamepad_async)
        self.root.after(100, self._tick)

    def _configure_styles(self):
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.style.configure(".", font=FONT)
        self.style.configure("App.TFrame", background=COLORS["surface"])
        self.style.configure("App.TEntry", padding=(8, 5), fieldbackground="#ffffff", foreground=COLORS["text"])
        self.style.configure(
            "App.TButton",
            padding=(14, 8),
            background=COLORS["surface_soft"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["surface_soft"],
            darkcolor=COLORS["border"],
            focusthickness=1,
            focuscolor=COLORS["border"],
        )
        self.style.map(
            "App.TButton",
            background=[("active", "#e4eee7"), ("disabled", "#e8ece8")],
            foreground=[("disabled", "#98a39d")],
        )
        self.style.configure(
            "Primary.TButton",
            padding=(18, 8),
            background=COLORS["accent"],
            foreground="#ffffff",
            bordercolor=COLORS["accent"],
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent"],
            focusthickness=1,
            focuscolor=COLORS["lime"],
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", COLORS["accent_hover"]), ("disabled", "#94aaa2")],
            foreground=[("disabled", "#edf4f0")],
        )
        self.style.configure(
            "Mode.TRadiobutton",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            padding=(2, 5),
            indicatorcolor="#ffffff",
            indicatormargin=3,
        )
        self.style.map(
            "Mode.TRadiobutton",
            background=[("active", COLORS["surface"])],
            foreground=[("active", COLORS["accent"])],
            indicatorcolor=[("selected", COLORS["accent"]), ("!selected", "#ffffff")],
        )
        self.style.configure(
            "App.TCheckbutton",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            padding=(2, 4),
            indicatorcolor="#ffffff",
        )
        self.style.map(
            "App.TCheckbutton",
            background=[("active", COLORS["surface"])],
            foreground=[("active", COLORS["accent"])],
            indicatorcolor=[("selected", COLORS["accent"]), ("!selected", "#ffffff")],
        )

    def _build_header(self, parent):
        header = tk.Frame(parent, bg=COLORS["bg"], highlightthickness=0)
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        tk.Label(
            header,
            text="地平线6 刷分助手",
            bg=COLORS["bg"],
            fg="#f5fff9",
            font=FONT_TITLE,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="虚拟手柄自动刷技能点 / 买车加点 / 组合循环",
            bg=COLORS["bg"],
            fg="#c7ddd4",
            font=FONT,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))
        ttk.Button(
            header,
            text="GitHub / 反馈",
            command=self.open_project_page,
            style="App.TButton",
        ).grid(row=0, column=1, rowspan=2, sticky="ne", padx=(12, 0), pady=(1, 0))

        guide = tk.Frame(
            header,
            bg=COLORS["bg_deep"],
            padx=12,
            pady=9,
            highlightbackground="#1f655b",
            highlightthickness=1,
        )
        guide.grid(row=2, column=0, columnspan=2, sticky="we")
        guide.columnconfigure(0, weight=1)
        tk.Label(
            guide,
            text="开始前请先把游戏设置为窗口模式",
            bg=COLORS["bg_deep"],
            fg="#ffffff",
            font=FONT_SECTION,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            guide,
            text="设置 -> 视频 -> 亮度 -> 全屏幕：关闭",
            bg=COLORS["bg_deep"],
            fg=COLORS["lime"],
            font=("Microsoft YaHei UI", 9, "bold"),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        driver = tk.Frame(guide, bg=COLORS["bg_deep"])
        driver.grid(row=2, column=0, sticky="we", pady=(7, 0))
        driver.columnconfigure(0, weight=1)
        tk.Label(
            driver,
            textvariable=self.driver_status_var,
            bg=COLORS["bg_deep"],
            fg="#d8e8df",
            font=FONT_SMALL,
            anchor="w",
        ).grid(row=0, column=0, sticky="we")
        self.driver_btn = ttk.Button(
            driver,
            text="安装/修复虚拟手柄驱动",
            command=self.open_driver_page,
            style="App.TButton",
        )
        self.driver_btn.grid(row=0, column=1, sticky="e", padx=(12, 0))
        return header

    def _card(self, parent, title, subtitle=None):
        outer = tk.Frame(
            parent,
            bg=COLORS["surface"],
            padx=12,
            pady=9,
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        outer.columnconfigure(0, weight=1)
        tk.Label(
            outer,
            text=title,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=FONT_SECTION,
            anchor="w",
        ).grid(row=0, column=0, sticky="we")
        next_row = 1
        if subtitle:
            tk.Label(
                outer,
                text=subtitle,
                bg=COLORS["surface"],
                fg=COLORS["muted"],
                font=FONT_SMALL,
                anchor="w",
            ).grid(row=1, column=0, sticky="we", pady=(1, 8))
            next_row = 2
        body = tk.Frame(outer, bg=COLORS["surface"])
        body.grid(row=next_row, column=0, sticky="we")
        body.columnconfigure(0, weight=1)
        outer.body = body
        return outer

    def _build_settings(self, parent):
        parent.columnconfigure(1, weight=1)
        self._field(parent, 0, "启动倒计时", self.startup_var, "秒")
        self.drive_widgets = self._field(parent, 1, "每圈前进时间", self.drive_var, "秒")
        self.drive_label, self.drive_entry, self.drive_unit = self.drive_widgets
        self.total_widgets = self._field(parent, 2, "刷图运行时间", self.total_var, "分钟，推荐 60；0=一直跑")
        self.total_label, self.total_entry, self.total_unit = self.total_widgets

    def _field(self, parent, row, label, var, unit):
        text = tk.Label(
            parent,
            text=label,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=FONT,
            anchor="w",
        )
        text.grid(row=row, column=0, sticky="w", pady=5, padx=(0, 10))
        entry = ttk.Entry(parent, textvariable=var, width=12, style="App.TEntry")
        entry.grid(row=row, column=1, sticky="e", pady=5)
        unit_label = tk.Label(
            parent,
            text=unit,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=FONT_SMALL,
            anchor="w",
        )
        unit_label.grid(row=row, column=2, sticky="w", pady=5, padx=(8, 0))
        return text, entry, unit_label

    def _build_actions(self, parent):
        for column in range(4):
            parent.columnconfigure(column, weight=1, uniform="actions")
        self.start_btn = ttk.Button(parent, text="开始", command=self.on_start, style="Primary.TButton")
        self.start_btn.grid(row=0, column=0, sticky="we", padx=(0, 8))
        self.stop_btn = ttk.Button(parent, text="停止", command=self.on_stop, state="disabled", style="App.TButton")
        self.stop_btn.grid(row=0, column=1, sticky="we", padx=8)
        self.log_btn = ttk.Button(parent, text="打开日志", command=self.open_log, style="App.TButton")
        self.log_btn.grid(row=0, column=2, sticky="we", padx=8)
        self.focus_btn = ttk.Button(parent, text="切回游戏", command=self.activate_game, style="App.TButton")
        self.focus_btn.grid(row=0, column=3, sticky="we", padx=(8, 0))

    def _build_prep(self, parent):
        parent.columnconfigure(0, weight=1)
        for row, step in enumerate(PREP_STEPS):
            self._prep_item(parent, row, step)

    def _prep_item(self, parent, row, step):
        item = tk.Frame(
            parent,
            bg=COLORS["surface_soft"],
            padx=8,
            pady=8,
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        item.grid(row=row, column=0, sticky="we", pady=(0, 8 if row < len(PREP_STEPS) - 1 else 0))
        item.columnconfigure(1, weight=1)

        thumb = self._load_thumbnail(step["image"], (176, 96))
        if thumb:
            image_label = tk.Label(item, image=thumb, bg=COLORS["surface_soft"], cursor="hand2")
            image_label.image = thumb
            image_label.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 10))
            image_label.bind("<Button-1>", lambda _event, item=step: self._show_image(item))
        else:
            image_label = tk.Label(
                item,
                text="截图",
                width=18,
                height=5,
                bg=COLORS["bg_deep"],
                fg="#ffffff",
                font=FONT_SMALL,
            )
            image_label.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 10))

        title = tk.Frame(item, bg=COLORS["surface_soft"])
        title.grid(row=0, column=1, sticky="we")
        tk.Label(
            title,
            text=step["number"],
            bg=COLORS["accent"],
            fg="#ffffff",
            font=("Microsoft YaHei UI", 8, "bold"),
            padx=6,
            pady=2,
        ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        tk.Label(
            title,
            text=step["title"],
            bg=COLORS["surface_soft"],
            fg=COLORS["text"],
            font=FONT_SECTION,
            anchor="w",
        ).grid(row=0, column=1, sticky="w")

        tk.Label(
            item,
            text=step["text"],
            bg=COLORS["surface_soft"],
            fg=COLORS["muted"],
            font=FONT_SMALL,
            justify="left",
            anchor="w",
            wraplength=255,
        ).grid(row=1, column=1, sticky="we", pady=(5, 4))

        footer = tk.Frame(item, bg=COLORS["surface_soft"])
        footer.grid(row=2, column=1, sticky="we")
        footer.columnconfigure(0, weight=1)
        tk.Label(
            footer,
            text="点击截图可查看大图",
            bg=COLORS["surface_soft"],
            fg=COLORS["muted"],
            font=FONT_SMALL,
        ).grid(row=0, column=0, sticky="w")
        if step.get("badge"):
            tk.Label(
                footer,
                text=step["badge"],
                bg=COLORS["bg_deep"],
                fg=COLORS["lime"],
                font=("Consolas", 9, "bold"),
                padx=6,
                pady=2,
            ).grid(row=0, column=1, sticky="e", padx=(12, 0))

    def _load_thumbnail(self, relative_path, size):
        path = resource_path(relative_path)
        try:
            image = Image.open(path)
            image = image.convert("RGB")
            source_ratio = image.width / image.height
            target_ratio = size[0] / size[1]
            if source_ratio > target_ratio:
                crop_width = int(image.height * target_ratio)
                left = (image.width - crop_width) // 2
                image = image.crop((left, 0, left + crop_width, image.height))
            else:
                crop_height = int(image.width / target_ratio)
                top = (image.height - crop_height) // 2
                image = image.crop((0, top, image.width, top + crop_height))
            image = image.resize(size, Image.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.image_refs.append(photo)
            return photo
        except Exception as exc:
            self.logger.warning("Unable to load prep image %s: %s", path, exc)
            return None

    def _show_image(self, step):
        path = resource_path(step["image"])
        try:
            image = Image.open(path)
        except Exception as exc:
            self._log(f"无法打开准备截图：{exc}")
            return

        max_size = (980, 620)
        image.thumbnail(max_size, Image.LANCZOS)
        photo = ImageTk.PhotoImage(image)

        popup = tk.Toplevel(self.root)
        popup.title(step["title"])
        popup.configure(bg=COLORS["bg"])
        popup.resizable(False, False)
        popup.transient(self.root)
        popup.preview_image = photo

        frame = tk.Frame(popup, bg=COLORS["bg"], padx=14, pady=14)
        frame.grid(row=0, column=0)
        tk.Label(
            frame,
            text=f"{step['number']} {step['title']}",
            bg=COLORS["bg"],
            fg="#ffffff",
            font=FONT_SECTION,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        tk.Label(frame, image=photo, bg=COLORS["bg"]).grid(row=1, column=0)
        ttk.Button(popup, text="关闭", command=popup.destroy, style="App.TButton").grid(
            row=1, column=0, sticky="e", padx=14, pady=(0, 14)
        )

    def _build_debug_buttons(self, parent):
        for column in range(3):
            parent.columnconfigure(column, weight=1, uniform="debug")
        self.confirm_btn = ttk.Button(parent, text="按A确认", command=lambda: self.tap_button("a"), style="App.TButton")
        self.confirm_btn.grid(row=0, column=0, sticky="we", padx=(0, 8))
        self.back_btn = ttk.Button(parent, text="按B返回", command=lambda: self.tap_button("b"), style="App.TButton")
        self.back_btn.grid(row=0, column=1, sticky="we", padx=8)
        self.detect_btn = ttk.Button(parent, text="识别一次", command=self.detect_once, style="App.TButton")
        self.detect_btn.grid(row=0, column=2, sticky="we", padx=(8, 0))

    def _build_advanced(self, parent):
        options = [
            ("游戏模式：点击本窗口不抢焦点", self.no_activate_var, self.apply_game_mode),
            ("开始后自动切回游戏窗口", self.auto_focus_var, None),
            ("只在游戏前台时计时（失焦自动暂停脚本）", self.require_foreground_var, None),
            ("切回后按 A 确认/恢复控制器", self.resume_var, None),
            ("失焦时尝试保持运行（实验性；建议先用无边框窗口）", self.keep_var, None),
        ]
        for row, (text, var, command) in enumerate(options):
            ttk.Checkbutton(
                parent,
                text=text,
                variable=var,
                command=command,
                style="App.TCheckbutton",
            ).grid(row=row, column=0, sticky="w", pady=1)

    def _add_mode_button(self, parent, mode, row):
        ttk.Radiobutton(
            parent,
            text=mode.label,
            variable=self.mode_var,
            value=mode.mode_id,
            command=self.apply_mode,
            style="Mode.TRadiobutton",
        ).grid(row=row, column=0, sticky="w")

    def _log(self, msg):
        self.logger.info(msg)
        self.log_q.put(msg)

    def _append(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _enqueue_toggle(self):
        self.logger.info("Ctrl+Alt+F8 pressed")
        self.command_q.put("toggle")

    def connect_gamepad_async(self):
        self.controller.connect_gamepad_async()

    def refresh_driver_status(self):
        status = check_vigembus()
        self.driver_status_var.set(status.message)
        if status.ok:
            self.driver_btn.config(text="驱动说明")
        else:
            self.driver_btn.config(text="安装/修复虚拟手柄驱动")
            if not self.driver_install_prompted:
                self.driver_install_prompted = True
                self.root.after(200, lambda: self.prompt_driver_install(status))
        self.logger.info("ViGEmBus GUI status: %s; detail=%s", status.message, status.detail)

    def open_driver_page(self):
        open_vigembus_download()
        self._log(f"已打开 ViGEmBus 官方下载页：{VIGEMBUS_INSTALL_URL}")
        self._log("下载安装后建议重启助手；如果系统要求重启电脑，请先重启。")

    def prompt_driver_install(self, status):
        self.logger.warning("Prompting ViGEmBus install: %s; detail=%s", status.message, status.detail)
        self._log(f"{status.message} 已自动打开 ViGEmBus 官方安装页。")
        self._log("请下载最新安装包并按提示安装；安装完成后建议重启电脑，再重新打开助手。")
        try:
            open_vigembus_download()
        except Exception as exc:
            self.logger.exception("Unable to open ViGEmBus page")
            self._log(f"无法自动打开安装页：{exc}")
        messagebox.showwarning(
            "需要安装虚拟手柄驱动",
            "这台电脑还没有可用的 ViGEmBus 虚拟手柄驱动。\n\n"
            "我已经为你打开官方安装页。请下载最新的 ViGEmBus 安装包，运行安装，并按 Windows 提示授权。\n\n"
            "安装完成后建议重启电脑，然后重新打开 Forza6Helper.exe。",
            parent=self.root,
        )

    def open_project_page(self):
        webbrowser.open(PROJECT_URL)
        self._log(f"已打开项目仓库：{PROJECT_URL}")

    def tap_button(self, name):
        self.controller.tap_button(name, auto_focus=self.auto_focus_var.get())

    def _tick(self):
        try:
            while True:
                command = self.command_q.get_nowait()
                if command == "toggle":
                    self.toggle_run(source="hotkey")
        except queue.Empty:
            pass

        try:
            while True:
                self._append(self.log_q.get_nowait())
        except queue.Empty:
            pass

        running = self.is_running()
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        self.root.after(100, self._tick)

    def is_running(self):
        return self.controller.is_running()

    def _format_number(self, value):
        if float(value).is_integer():
            return f"{value:.1f}"
        return f"{value:.2f}".rstrip("0").rstrip(".")

    def _read_number(self, label, var, default, minimum=0.0):
        raw = var.get().strip()
        try:
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError
        except ValueError:
            value = float(default)
            var.set(self._format_number(value))
            self._log(f"参数校验：{label} 输入无效，已改为 {self._format_number(value)}。")
            return value

        if value < minimum:
            value = float(minimum)
            var.set(self._format_number(value))
            self._log(f"参数校验：{label} 不能小于 {self._format_number(minimum)}，已自动修正。")
            return value

        normalized = self._format_number(value)
        if raw != normalized:
            var.set(normalized)
        return value

    def _settings_from_ui(self, source):
        mode = get_mode(self.mode_var.get())
        total_label = "每轮刷图时间" if mode.mode_id == MODE_COMBO else "刷图运行时间"
        return RuntimeSettings(
            mode_id=self.mode_var.get(),
            startup_delay=self._read_number("启动倒计时", self.startup_var, config.STARTUP_DELAY),
            drive_seconds=self._read_number("每圈前进时间", self.drive_var, config.DRIVE_SECONDS),
            total_minutes=self._read_number(total_label, self.total_var, 0.0),
            keep_active=self.keep_var.get(),
            auto_focus=self.auto_focus_var.get(),
            no_activate=self.no_activate_var.get(),
            require_foreground=self.require_foreground_var.get(),
            resume_after_focus=self.resume_var.get(),
            source=source,
        )

    def on_start(self):
        self.start_run(source="button")

    def start_run(self, source="button"):
        self.controller.start(self._settings_from_ui(source))

    def on_stop(self, source="button"):
        self.controller.stop(source=source)

    def toggle_run(self, source="hotkey"):
        if self.is_running():
            self.on_stop(source=source)
        else:
            self.start_run(source=source)

    def activate_game(self):
        return self.controller.activate_game()

    def apply_mode(self):
        mode = get_mode(self.mode_var.get())
        defaults = mode.defaults
        self.no_activate_var.set(defaults.no_activate)
        self.auto_focus_var.set(defaults.auto_focus)
        self.require_foreground_var.set(defaults.require_foreground)
        self.keep_var.set(defaults.keep_active)
        self.resume_var.set(defaults.resume_after_focus)
        if mode.mode_id == MODE_SKILL_POINTS and self.total_var.get().strip() == "10.0":
            self.total_var.set("0.0")
        self.hint_var.set(mode.hint)
        self._log(mode.log_message)
        self.refresh_field_visibility()
        self.apply_game_mode()

    def refresh_debug_visibility(self):
        show = self.show_debug_var.get()
        selected_mode = get_mode(self.mode_var.get())
        if not show and not selected_mode.product_visible:
            self.mode_var.set(DEFAULT_MODE_ID)
            self.apply_mode()
            return

        if show:
            self.debug_mode_frame.grid()
            self.debug_buttons_frame.grid()
            self.advanced_frame.grid()
        else:
            self.debug_mode_frame.grid_remove()
            self.debug_buttons_frame.grid_remove()
            self.advanced_frame.grid_remove()
        self.refresh_field_visibility()

    def refresh_field_visibility(self):
        mode = get_mode(self.mode_var.get())
        if mode.mode_id == MODE_COMBO:
            self.total_label.config(text="每轮刷图时间")
            self.total_unit.config(text="推荐 60；0=默认 90；买车不计时")
        elif mode.mode_id == MODE_BUY_CAR:
            self.total_label.config(text="刷图运行时间")
            self.total_unit.config(text="买车加点不计入刷图时间")
        elif mode.mode_id == MODE_SKILL_POINTS:
            self.total_label.config(text="刷图运行时间")
            self.total_unit.config(text="分钟，推荐 60；0=一直跑")
        else:
            self.total_label.config(text="总运行时间")
            self.total_unit.config(text="分钟，0=一直跑")

        if mode.uses_drive_seconds or self.show_debug_var.get():
            for widget in self.drive_widgets:
                widget.grid()
        else:
            for widget in self.drive_widgets:
                widget.grid_remove()

        if mode.mode_id == MODE_BUY_CAR and not self.show_debug_var.get():
            for widget in self.total_widgets:
                widget.grid_remove()
        else:
            for widget in self.total_widgets:
                widget.grid()

    def detect_once(self):
        if self.auto_focus_var.get():
            self.activate_game()
        try:
            detection = self.controller.detect_once(self.mode_var.get())
        except Exception as exc:
            self.logger.exception("Manual detection failed")
            self._log(f"识别失败：{exc}")
            return
        scores = ", ".join(f"{k}={v:.3f}" for k, v in detection.scores.items())
        self._log(f"识别一次：{detection.state} conf={detection.confidence:.2f}；{scores}")
        if getattr(detection, "ocr_text", ""):
            self._log(f"OCR：{detection.ocr_text[:180]}")
        self.logger.info(
            "Manual detection state=%s confidence=%.3f scores=%s",
            detection.state,
            detection.confidence,
            scores,
        )

    def apply_game_mode(self):
        try:
            self.root.update_idletasks()
            ok = focus.set_no_activate(
                self.root.winfo_id(),
                enabled=self.no_activate_var.get(),
                topmost=self.no_activate_var.get(),
                logger=self.logger,
            )
        except Exception as exc:
            self._log(f"游戏模式设置失败：{exc}")
            return False

        if ok:
            state = "开启" if self.no_activate_var.get() else "关闭"
            self._log(f"游戏模式已{state}。")
        return ok

    def open_log(self):
        try:
            LOG_PATH.touch(exist_ok=True)
            os.startfile(LOG_PATH)
            self.logger.info("Opened log file")
        except Exception as exc:
            self._log(f"无法打开日志文件：{exc}")

    def on_close(self):
        self.logger.info("Window closing")
        self.hotkey.stop()
        self.controller.close()
        self.root.after(200, self.root.destroy)


def main():
    instance = SingleInstance()
    if not instance.acquired:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("地平线6 刷分助手", "助手已经在运行。请先关闭旧窗口，避免创建多个虚拟手柄。")
        root.destroy()
        return
    root = tk.Tk()
    root._single_instance = instance
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
