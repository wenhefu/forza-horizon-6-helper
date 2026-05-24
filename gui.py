"""Simple GUI for the FH6 skill-point farm. Package to .exe with build.bat (on Windows)."""
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from app_logging import LOG_PATH, log_startup_diagnostics, setup_logging
from buy_car_runner import BuyCarRunner
import config
import focus
from gamepad import Gamepad
from hotkeys import GlobalHotkey
from runner import Runner
from sequences import farm_sequence
from single_instance import SingleInstance
from smart_runner import SmartRunner


class App:
    def __init__(self, root):
        self.root = root
        root.title("地平线6 刷分助手")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.log_q = queue.Queue()
        self.command_q = queue.Queue()
        self.logger = setup_logging()
        log_startup_diagnostics(self.logger)

        self.pad = None
        self.pad_error = None
        self.pad_lock = threading.Lock()

        self.runner = Runner(on_log=self._log, logger=self.logger, pad_provider=self.get_gamepad)
        self.smart_runner = SmartRunner(on_log=self._log, logger=self.logger, pad_provider=self.get_gamepad)
        self.buy_car_runner = BuyCarRunner(on_log=self._log, logger=self.logger, pad_provider=self.get_gamepad)
        self.keeper = None
        self.hotkey = GlobalHotkey(on_press=self._enqueue_toggle, on_log=self._log)

        self.startup_var = tk.StringVar(value=str(config.STARTUP_DELAY))
        self.drive_var = tk.StringVar(value=str(config.DRIVE_SECONDS))
        self.total_var = tk.StringVar(value=str(config.TOTAL_MINUTES))
        self.keep_var = tk.BooleanVar(value=False)
        self.auto_focus_var = tk.BooleanVar(value=True)
        self.no_activate_var = tk.BooleanVar(value=True)
        self.require_foreground_var = tk.BooleanVar(value=True)
        self.resume_var = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value="skill_points")
        self.hint_var = tk.StringVar()

        frm = ttk.Frame(root, padding=12)
        frm.grid(row=0, column=0)

        mode_box = ttk.LabelFrame(frm, text="运行模式", padding=6)
        mode_box.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 6))
        ttk.Radiobutton(mode_box, text="模式一：刷技能点（EventLab）",
                        variable=self.mode_var, value="skill_points",
                        command=self.apply_mode).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(mode_box, text="模式二：买车加点（先买22B）",
                        variable=self.mode_var, value="buy_car",
                        command=self.apply_mode).grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(mode_box, text="模式三：前台计时（兜底）",
                        variable=self.mode_var, value="foreground",
                        command=self.apply_mode).grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(mode_box, text="模式四：后台尝试（实验，不保证）",
                        variable=self.mode_var, value="background",
                        command=self.apply_mode).grid(row=3, column=0, sticky="w")

        fields = [
            ("启动倒计时（秒）", self.startup_var),
            ("每圈前进时间（秒）", self.drive_var),
            ("总运行时间（分钟，0=一直跑，刷技能点默认0）", self.total_var),
        ]
        r = 1
        for label, var in fields:
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(frm, textvariable=var, width=10).grid(row=r, column=1, pady=3)
            r += 1

        btns = ttk.Frame(frm)
        btns.grid(row=r, column=0, columnspan=2, pady=(8, 4))
        r += 1
        self.start_btn = ttk.Button(btns, text="开始", command=self.on_start)
        self.start_btn.grid(row=0, column=0, padx=4)
        self.stop_btn = ttk.Button(btns, text="停止", command=self.on_stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=4)
        self.log_btn = ttk.Button(btns, text="打开日志", command=self.open_log)
        self.log_btn.grid(row=0, column=2, padx=4)
        self.focus_btn = ttk.Button(btns, text="切回游戏", command=self.activate_game)
        self.focus_btn.grid(row=0, column=3, padx=4)
        self.detect_btn = ttk.Button(btns, text="识别一次", command=self.detect_once)
        self.detect_btn.grid(row=1, column=2, padx=4, pady=(6, 0))
        self.confirm_btn = ttk.Button(btns, text="按A确认", command=lambda: self.tap_button("a"))
        self.confirm_btn.grid(row=1, column=0, padx=4, pady=(6, 0))
        self.back_btn = ttk.Button(btns, text="按B返回", command=lambda: self.tap_button("b"))
        self.back_btn.grid(row=1, column=1, padx=4, pady=(6, 0))

        ttk.Label(frm, text="高级（切换模式会自动设置，可手动覆盖）",
                  foreground="#888").grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 0))
        r += 1

        ttk.Checkbutton(frm, text="游戏模式：点击本窗口不抢焦点",
                        variable=self.no_activate_var,
                        command=self.apply_game_mode).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Checkbutton(frm, text="开始后自动切回游戏窗口",
                        variable=self.auto_focus_var).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Checkbutton(frm, text="只在游戏前台时计时（失焦自动暂停脚本）",
                        variable=self.require_foreground_var).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Checkbutton(frm, text="切回后按 A 确认/恢复控制器",
                        variable=self.resume_var).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Checkbutton(frm, text="失焦时尝试保持运行（实验性；建议先用无边框窗口）",
                        variable=self.keep_var).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Label(frm, textvariable=self.hint_var,
                  foreground="#666", wraplength=320).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        self.log = scrolledtext.ScrolledText(frm, width=46, height=12, state="disabled")
        self.log.grid(row=r, column=0, columnspan=2, pady=(8, 0))
        self._log(f"日志文件：{LOG_PATH}")
        self.hotkey.start()
        self.root.after(300, self.apply_mode)
        self.root.after(500, self.connect_gamepad_async)

        self.root.after(100, self._tick)

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
        threading.Thread(target=self._connect_gamepad_worker, name="gamepad-connect", daemon=True).start()

    def _connect_gamepad_worker(self):
        try:
            self.get_gamepad()
            self._log("虚拟手柄已常驻连接。")
        except Exception as exc:
            self.logger.exception("Persistent gamepad connection failed")
            self._log(f"虚拟手柄连接失败：{exc}")

    def get_gamepad(self):
        with self.pad_lock:
            if self.pad:
                return self.pad
            if self.pad_error:
                raise self.pad_error
            try:
                self.pad = Gamepad(logger=self.logger)
                return self.pad
            except Exception as exc:
                self.pad_error = exc
                raise

    def tap_button(self, name):
        if self.auto_focus_var.get():
            self.activate_game()
        try:
            pad = self.get_gamepad()
            pad.tap(name, hold=0.15)
            self._log(f"已按 {name.upper()}。")
        except Exception as exc:
            self.logger.exception("Manual tap failed")
            self._log(f"按键失败：{exc}")

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
        return self.runner.is_running() or self.smart_runner.is_running() or self.buy_car_runner.is_running()

    def _num(self, var, default):
        try:
            return float(var.get())
        except ValueError:
            return default

    def on_start(self):
        self.start_run(source="button")

    def start_run(self, source="button"):
        startup = self._num(self.startup_var, config.STARTUP_DELAY)
        drive = self._num(self.drive_var, config.DRIVE_SECONDS)
        minutes = self._num(self.total_var, config.TOTAL_MINUTES)
        total = None if minutes <= 0 else minutes * 60
        if self.mode_var.get() in ("smart", "skill_points"):
            if total is None:
                self._log("刷技能点模式：总运行时间为 0，会一直跑到你手动停止。")
            else:
                self._log(f"刷技能点模式：总运行时间为 {minutes:.1f} 分钟，到点会自动停止并回正手柄。")
        self.logger.info(
            "Start requested source=%s startup=%.2f drive=%.2f minutes=%.2f keep_active=%s auto_focus=%s require_foreground=%s resume=%s no_activate=%s",
            source,
            startup,
            drive,
            minutes,
            self.keep_var.get(),
            self.auto_focus_var.get(),
            self.require_foreground_var.get(),
            self.resume_var.get(),
            self.no_activate_var.get(),
        )
        if self.auto_focus_var.get():
            self.activate_game()
        if self.keep_var.get():
            self.keeper = focus.KeepActive(title_substr=config.GAME_TITLE, on_log=self._log)
            self.keeper.start()
        if self.mode_var.get() in ("smart", "skill_points"):
            self.smart_runner.start(
                startup_delay=startup,
                total_seconds=total,
                auto_focus=self.auto_focus_var.get(),
                require_foreground=self.require_foreground_var.get(),
            )
            return
        if self.mode_var.get() == "buy_car":
            self.buy_car_runner.start(
                startup_delay=startup,
                total_seconds=total,
                auto_focus=self.auto_focus_var.get(),
                require_foreground=self.require_foreground_var.get(),
            )
            return
        self.runner.start(farm_sequence(drive_seconds=drive),
                          startup_delay=startup,
                          total_seconds=total,
                          resume_button="a" if self.resume_var.get() else None,
                          require_foreground=self.require_foreground_var.get(),
                          foreground_check=lambda: focus.is_foreground(config.GAME_TITLE),
                          on_focus_lost=self._on_focus_lost,
                          on_focus_restored=self._on_focus_restored)

    def on_stop(self, source="button"):
        self.logger.info("Stop requested source=%s", source)
        self.runner.stop()
        self.smart_runner.stop()
        self.buy_car_runner.stop()
        if self.keeper:
            self.keeper.stop()
            self.keeper = None

    def toggle_run(self, source="hotkey"):
        if self.is_running():
            self.on_stop(source=source)
        else:
            self.start_run(source=source)

    def activate_game(self):
        return focus.activate_window(
            title_substr=config.GAME_TITLE,
            on_log=self._log,
            logger=self.logger,
        )

    def _on_focus_lost(self):
        if self.auto_focus_var.get():
            focus.activate_window(
                title_substr=config.GAME_TITLE,
                on_log=self._log,
                logger=self.logger,
            )

    def _on_focus_restored(self):
        # Leave menu recovery to the user or the explicit checkbox.
        pass

    def apply_mode(self):
        if self.mode_var.get() in ("smart", "skill_points"):
            self.no_activate_var.set(True)
            self.auto_focus_var.set(True)
            self.require_foreground_var.set(True)
            self.keep_var.set(False)
            self.resume_var.set(False)
            if self.total_var.get().strip() == "10.0":
                self.total_var.set("0.0")
            self.hint_var.set("刷技能点：EventLab 智能识别，不盲计时。图1先校准到开始赛事再按A，图2保持油门，"
                              "图3按X，图4按A；总运行时间默认0=一直跑；暂停菜单按B返回，截图只在内存中处理。")
            self._log("已切到【刷技能点】模式。")
        elif self.mode_var.get() == "buy_car":
            self.no_activate_var.set(True)
            self.auto_focus_var.set(True)
            self.require_foreground_var.set(True)
            self.keep_var.set(False)
            self.resume_var.set(False)
            self.hint_var.set("买车加点：第一段先购买默认斯巴鲁 22B。会按 Menu 打开暂停菜单，"
                              "进入车展购买 22B，买车辆熟练度抽奖精灵后回车展循环；截图只在内存中处理。")
            self._log("已切到【买车加点】模式（买 22B + 熟练度抽奖精灵循环）。")
        elif self.mode_var.get() == "background":
            self.no_activate_var.set(True)
            self.auto_focus_var.set(False)
            self.require_foreground_var.set(False)
            self.keep_var.set(True)
            self.hint_var.set("后台尝试：可去用别的窗口；建议游戏用无边框窗口。"
                              "地平线很可能失焦就暂停，本模式不保证有效，但零封号风险。")
            self._log("已切到【后台尝试】模式（非注入，不保证）。")
        else:
            self.no_activate_var.set(True)
            self.auto_focus_var.set(True)
            self.require_foreground_var.set(True)
            self.keep_var.set(False)
            self.hint_var.set("前台挂机：游戏保持前台，期间请勿操作其他窗口；"
                              "失焦会自动暂停计时并尝试切回。")
            self._log("已切到【前台挂机】模式（推荐，稳）。")
        self.apply_game_mode()

    def detect_once(self):
        if self.auto_focus_var.get():
            self.activate_game()
        try:
            if self.mode_var.get() == "buy_car":
                detection = self.buy_car_runner.detect_once()
            else:
                detection = self.smart_runner.detect_once()
        except Exception as exc:
            self.logger.exception("Manual detection failed")
            self._log(f"识别失败：{exc}")
            return
        scores = ", ".join(f"{k}={v:.3f}" for k, v in detection.scores.items())
        self._log(f"识别一次：{detection.state} conf={detection.confidence:.2f}；{scores}")
        if getattr(detection, "ocr_text", ""):
            self._log(f"OCR：{detection.ocr_text[:180]}")
        self.logger.info("Manual detection state=%s confidence=%.3f scores=%s",
                         detection.state, detection.confidence, scores)

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
        self.runner.stop()
        self.smart_runner.stop()
        self.buy_car_runner.stop()
        if self.pad:
            self.pad.neutral()
        if self.keeper:
            self.keeper.stop()
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
