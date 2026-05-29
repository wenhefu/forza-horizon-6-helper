from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import focus
from ocr_engine import OcrReader
from v2.semantic import ForzaSemanticAnalyzer
from v3.dataset import generate_yolo_dataset
from v3.dataset_audit import audit_dataset, render_markdown, write_report
from v3.hybrid import HybridVisionRecognizer
from v3.sample_collector import SampleCollector
from v3.yolo_detector import DEFAULT_MODEL, YoloOnnxDetector, resolve_asset_path
from window_capture import capture_client, capture_client_printwindow


class VisionRecognizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("地平线6 Vision 最强识别版")
        self.root.geometry("1360x820")
        self.root.minsize(1160, 700)
        self.logger = logging.getLogger("forza6helper.v3")

        self.ocr = OcrReader(logger=self.logger)
        self.analyzer = ForzaSemanticAnalyzer()
        self.detector = None
        self.recognizer = None
        self.collector = SampleCollector()

        self.live = False
        self.busy = False
        self.last_frame = None
        self.last_ocr_items = []
        self.last_v2 = None
        self.last_v3 = None
        self.preview_photo = None

        self.title_var = tk.StringVar(value="Forza")
        self.model_var = tk.StringVar(value=str(DEFAULT_MODEL))
        self.min_conf_var = tk.DoubleVar(value=0.42)
        self.interval_var = tk.DoubleVar(value=1.0)
        self.full_ocr_var = tk.BooleanVar(value=True)
        self.region_ocr_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="V3 独立识别实验版：不注入、不 hook、不 fake-focus、不发送输入。")
        self.screen_var = tk.StringVar(value="页面: 未识别")
        self.action_var = tk.StringVar(value="动作建议: -")

        self._build_style()
        self._build_ui()
        self.reload_model()

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Root.TFrame", background="#0d372f")
        style.configure("Panel.TFrame", background="#f6faf7", relief="flat")
        style.configure("Title.TLabel", background="#0d372f", foreground="#f7fff9", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Sub.TLabel", background="#0d372f", foreground="#c4e4d7", font=("Microsoft YaHei UI", 9))
        style.configure("PanelTitle.TLabel", background="#f6faf7", foreground="#0e2f28", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Panel.TLabel", background="#f6faf7", foreground="#1c3e37", font=("Microsoft YaHei UI", 9))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_ui(self):
        root = ttk.Frame(self.root, style="Root.TFrame", padding=14)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, style="Root.TFrame")
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="地平线6 Vision 最强识别版", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="窗口截图 / YOLO ONNX / 小区域 OCR / V2 规则融合 / 按完再验证动作建议",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(root, style="Root.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Panel.TFrame", padding=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(3, weight=1)
        left.columnconfigure(0, weight=1)

        controls = ttk.Frame(left, style="Panel.TFrame")
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(8, weight=1)
        ttk.Label(controls, text="窗口标题", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.title_var, width=14).grid(row=0, column=1, padx=(6, 12))
        ttk.Label(controls, text="OCR阈值", style="Panel.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(controls, from_=0.10, to=0.90, increment=0.02, textvariable=self.min_conf_var, width=6).grid(row=0, column=3, padx=(6, 12))
        ttk.Label(controls, text="间隔", style="Panel.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(controls, from_=0.4, to=5.0, increment=0.1, textvariable=self.interval_var, width=6).grid(row=0, column=5, padx=(6, 12))
        ttk.Checkbutton(controls, text="全图 OCR 兜底", variable=self.full_ocr_var).grid(row=0, column=6, sticky="w", padx=(0, 8))
        ttk.Checkbutton(controls, text="小区域 OCR", variable=self.region_ocr_var).grid(row=0, column=7, sticky="w")

        model_row = ttk.Frame(left, style="Panel.TFrame")
        model_row.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        model_row.columnconfigure(1, weight=1)
        ttk.Label(model_row, text="ONNX模型", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(model_row, textvariable=self.model_var).grid(row=0, column=1, sticky="ew", padx=(6, 8))
        ttk.Button(model_row, text="重新加载", command=self.reload_model).grid(row=0, column=2)

        button_bar = ttk.Frame(left, style="Panel.TFrame")
        button_bar.grid(row=2, column=0, sticky="w", pady=(10, 10))
        ttk.Button(button_bar, text="识别一次", style="Accent.TButton", command=self.capture_once).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="开始实时", command=self.start_live).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="停止", command=self.stop_live).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="保存训练样本", command=self.save_training_sample).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="生成YOLO数据集", command=self.generate_dataset).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="审计样本缺口", command=self.audit_samples).pack(side="left")

        self.canvas = tk.Canvas(left, bg="#102e29", highlightthickness=0)
        self.canvas.grid(row=3, column=0, sticky="nsew")

        right = ttk.Frame(body, style="Panel.TFrame", padding=12)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)
        summary = ttk.Frame(right, style="Panel.TFrame")
        summary.grid(row=0, column=0, sticky="ew")
        summary.columnconfigure(0, weight=1)
        ttk.Label(summary, textvariable=self.screen_var, style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.action_var, style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(summary, text="复制结果", command=self.copy_result).grid(row=0, column=1, rowspan=2, sticky="e")

        ttk.Label(right, text="融合识别结果", style="PanelTitle.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 6))
        self.text = tk.Text(
            right,
            wrap="word",
            bg="#082c27",
            fg="#ecfff5",
            insertbackground="#ecfff5",
            relief="flat",
            font=("Consolas", 10),
            padx=10,
            pady=10,
        )
        self.text.grid(row=2, column=0, sticky="nsew")
        self.text.insert("1.0", "点击“识别一次”开始。\n")
        ttk.Label(root, textvariable=self.status_var, style="Sub.TLabel").pack(fill="x", pady=(10, 0))

    def _ensure_recognizer(self):
        model_path = self.model_var.get().strip()
        resolved_model_path = str(resolve_asset_path(model_path))
        if self.detector and self.detector.stats.model_path == resolved_model_path:
            return
        self.detector = YoloOnnxDetector(model_path=model_path)
        self.recognizer = HybridVisionRecognizer(detector=self.detector, ocr_reader=self.ocr, analyzer=self.analyzer)

    def reload_model(self):
        self.detector = None
        self._ensure_recognizer()
        status = self.detector.stats
        if status.loaded:
            self.status_var.set(f"ONNX模型已加载：{status.model_path} provider={status.provider}")
        else:
            self.status_var.set(f"ONNX模型未加载：{status.error or status.model_path}")

    def start_live(self):
        self.live = True
        self.status_var.set("实时识别已开启。V3 不会发送任何输入。")
        self._schedule_live(0)

    def stop_live(self):
        self.live = False
        self.status_var.set("实时识别已停止。")

    def capture_once(self):
        self._run_capture_async()

    def _schedule_live(self, delay_ms=None):
        if not self.live:
            return
        if delay_ms is None:
            delay_ms = int(max(0.4, float(self.interval_var.get() or 1.0)) * 1000)
        self.root.after(delay_ms, self._live_tick)

    def _live_tick(self):
        if not self.live:
            return
        self._run_capture_async()
        self._schedule_live()

    def _run_capture_async(self):
        if self.busy:
            return
        self.busy = True
        self.status_var.set("正在截图、模型推理和 OCR...")
        threading.Thread(target=self._capture_worker, daemon=True).start()

    def _capture_worker(self):
        started = time.perf_counter()
        try:
            self._ensure_recognizer()
            title = self.title_var.get().strip() or "Forza"
            hwnd = focus.find_window(title)
            if not hwnd:
                raise RuntimeError(f"没找到标题包含“{title}”的窗口")
            try:
                frame = capture_client_printwindow(hwnd)
            except Exception:
                frame = capture_client(hwnd)
            items = []
            if bool(self.full_ocr_var.get()):
                items = self.ocr.read_frame(frame, min_confidence=float(self.min_conf_var.get() or 0.42))
            v3 = self.recognizer.analyze_frame(
                frame,
                ocr_items=items,
                run_full_ocr=False,
                run_region_ocr=bool(self.region_ocr_var.get()),
                min_confidence=float(self.min_conf_var.get() or 0.42),
            )
            elapsed = (time.perf_counter() - started) * 1000.0
            self.root.after(0, lambda: self._update_result(frame, items, v3, elapsed, None))
        except Exception as exc:
            self.root.after(0, lambda: self._update_result(None, [], None, 0.0, exc))

    def _update_result(self, frame, items, v3, elapsed_ms, error):
        self.busy = False
        if error:
            self.status_var.set(f"识别失败：{error}")
            return
        self.last_frame = frame
        self.last_ocr_items = items
        self.last_v3 = v3
        first_action = v3.actions[0] if v3.actions else None
        scope = f" / {v3.tab_scope}" if v3.tab_scope else ""
        self.screen_var.set(
            f"页面: {v3.screen}  节点: {v3.ui_title or '未知'}  分页: {v3.active_tab or '未知'}{scope}  置信度: {v3.confidence:.2f}"
        )
        filter_suffix = self._filter_summary(v3)
        self.action_var.set(
            f"动作建议: {(first_action.button or '不按键') if first_action else '-'}"
            f" / {(first_action.name if first_action else '-')}"
            f"{('  |  ' + filter_suffix) if filter_suffix else ''}"
        )
        self.text.delete("1.0", "end")
        self.text.insert("1.0", v3.as_text())
        self._draw_preview(frame, v3)
        model_ms = self.detector.stats.last_latency_ms if self.detector else 0.0
        self.status_var.set(
            f"完成：detections={len(v3.detections)} total={elapsed_ms:.1f}ms model={model_ms:.1f}ms。V3 没有发送任何输入。"
        )

    def _filter_summary(self, v3):
        state = getattr(v3, "filter_state", {}) or {}
        if not state.get("visible"):
            return ""
        checked = state.get("favorite_checked")
        if checked is True:
            checked_text = "收藏已勾选"
        elif checked is False:
            checked_text = "收藏未勾选"
        else:
            checked_text = "收藏状态未知"
        focused = state.get("focused_row") or "未知"
        return f"筛选: 焦点={focused}，{checked_text}"

    def _draw_preview(self, frame, v3):
        try:
            from PIL import ImageDraw, ImageTk
            from v3.frame_utils import frame_to_pil
        except Exception as exc:
            self.canvas.delete("all")
            self.canvas.create_text(20, 20, anchor="nw", fill="#ecfff5", text=f"预览不可用：{exc}")
            return
        image = frame_to_pil(frame)
        canvas_w = max(320, self.canvas.winfo_width())
        canvas_h = max(220, self.canvas.winfo_height())
        scale = min(canvas_w / image.width, canvas_h / image.height)
        preview_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        image = image.resize(preview_size)
        draw = ImageDraw.Draw(image)
        left, top, right, bottom = v3.content_region
        draw.rectangle(
            [left * preview_size[0], top * preview_size[1], right * preview_size[0], bottom * preview_size[1]],
            outline="#00e0aa",
            width=2,
        )
        for detection in v3.detections:
            x1, y1, x2, y2 = detection.bbox
            color = "#ffec33" if detection.source.startswith("rule") else "#5ce1ff"
            draw.rectangle([x1 * preview_size[0], y1 * preview_size[1], x2 * preview_size[0], y2 * preview_size[1]], outline=color, width=3)
            draw.text((x1 * preview_size[0] + 4, y1 * preview_size[1] + 4), detection.label, fill=color)
        for region in v3.ocr_regions:
            x1, y1, x2, y2 = region.bbox
            color = "#ff4fd8" if region.name.endswith("_focus") else "#ffffff"
            draw.rectangle([x1 * preview_size[0], y1 * preview_size[1], x2 * preview_size[0], y2 * preview_size[1]], outline=color, width=2)
            draw.text((x1 * preview_size[0] + 4, max(0, y1 * preview_size[1] - 14)), region.name, fill=color)
        filter_state = getattr(v3, "filter_state", {}) or {}
        checkbox_bbox = filter_state.get("checkbox_bbox")
        if filter_state.get("visible") and checkbox_bbox:
            x1, y1, x2, y2 = checkbox_bbox
            checked = filter_state.get("favorite_checked")
            if checked is True:
                color = "#36ff7a"
                label = "favorite checked"
            elif checked is False:
                color = "#ffb84d"
                label = "favorite empty"
            else:
                color = "#ffffff"
                label = "favorite unknown"
            draw.rectangle([x1 * preview_size[0], y1 * preview_size[1], x2 * preview_size[0], y2 * preview_size[1]], outline=color, width=3)
            draw.text((x1 * preview_size[0] + 4, max(0, y1 * preview_size[1] - 16)), label, fill=color)
        self.preview_photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        x = (canvas_w - preview_size[0]) // 2
        y = (canvas_h - preview_size[1]) // 2
        self.canvas.create_image(x, y, anchor="nw", image=self.preview_photo)

    def save_training_sample(self):
        if not self.last_frame or not self.last_v3:
            messagebox.showinfo("Vision 样本", "还没有识别结果。")
            return
        try:
            path = self.collector.save_sample(
                self.last_frame,
                self.title_var.get().strip() or "Forza",
                self.last_ocr_items,
                self.recognizer.analyzer.analyze(self.last_frame, self.last_ocr_items),
                candidates=self.last_v3.detections,
                capture_method="gui-v3",
                extra_metadata={"v3_understanding": self.last_v3.to_dict()},
            )
            self.status_var.set(f"训练样本已保存：{path}")
        except Exception as exc:
            messagebox.showerror("Vision 样本", str(exc))

    def generate_dataset(self):
        try:
            summary = generate_yolo_dataset()
            self.status_var.set(f"YOLO数据集已生成：{summary['dataset_root']} images={summary['images']}")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", json.dumps(summary, ensure_ascii=False, indent=2))
        except Exception as exc:
            messagebox.showerror("YOLO 数据集", str(exc))

    def audit_samples(self):
        try:
            report = audit_dataset()
            json_path, md_path = write_report(report)
            self.status_var.set(f"样本缺口审计完成：{md_path}")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", render_markdown(report))
        except Exception as exc:
            messagebox.showerror("样本缺口审计", str(exc))

    def copy_result(self):
        if not self.last_v3:
            messagebox.showinfo("Vision 识别", "还没有识别结果。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_v3.as_text())
        self.status_var.set("融合识别结果已复制到剪贴板。")


def main():
    logging.basicConfig(level=logging.INFO)
    root = tk.Tk()
    VisionRecognizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
