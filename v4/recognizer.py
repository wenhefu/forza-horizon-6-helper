from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any

import focus
from ocr_engine import OcrReader
from screen_detector import ForzaScreenDetector
from v2.semantic import ForzaSemanticAnalyzer
from v3.hybrid import HybridVisionRecognizer
from v3.yolo_detector import DEFAULT_MODEL, YoloOnnxDetector
from window_capture import capture_client, capture_client_printwindow


@dataclass
class V4Snapshot:
    frame: Any
    window_title: str
    capture_method: str
    ocr_items: list
    v3: Any
    smart_state: str = ""
    smart_confidence: float = 0.0
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "window_title": self.window_title,
            "capture_method": self.capture_method,
            "ocr_items": len(self.ocr_items),
            "v3": self.v3.to_dict() if hasattr(self.v3, "to_dict") else {},
            "smart_state": self.smart_state,
            "smart_confidence": self.smart_confidence,
            "elapsed_ms": self.elapsed_ms,
        }


class V4Recognizer:
    """Capture Forza and run the V3 hybrid recognizer plus V1 race detector."""

    def __init__(
        self,
        title: str = "Forza",
        model_path: str | None = None,
        min_confidence: float = 0.42,
        logger=None,
        capture_engine=None,
    ):
        self.title = title
        self.min_confidence = float(min_confidence)
        self.logger = logger or logging.getLogger("forza6helper.v4")
        # Optional v5.capture_engine.CaptureEngine. When set + running + fresh, its
        # latest frame is used instead of a synchronous grab. None (the default for
        # every current caller) leaves the V4 capture path byte-for-byte unchanged.
        self.capture_engine = capture_engine
        self.ocr = OcrReader(logger=self.logger)
        self.analyzer = ForzaSemanticAnalyzer()
        self.detector = YoloOnnxDetector(model_path=model_path or DEFAULT_MODEL)
        self.hybrid = HybridVisionRecognizer(
            detector=self.detector,
            ocr_reader=self.ocr,
            analyzer=self.analyzer,
        )
        self.smart_detector = ForzaScreenDetector()

    def capture(
        self, full_ocr: bool = True, region_ocr: bool = True, max_age_ms: float = 250.0,
        skip_smart: bool = False, downscale_width: int | None = None,
    ) -> V4Snapshot:
        start = time.perf_counter()
        frame = None
        method = ""
        title = self.title
        ce = self.capture_engine
        if ce is not None and ce.is_running():
            cand, age_ms = ce.get_latest_frame()
            if cand is not None and age_ms <= max_age_ms:
                frame, method = cand, "dxcam"  # fast path: continuous-capture frame
        if frame is None:
            # Default V4 path -- unchanged when no capture_engine is set, or when
            # the latest engine frame is stale (page just changed) -> sync re-grab.
            hwnd = focus.find_window(self.title)
            if not hwnd:
                raise RuntimeError(f"No game window title contains {self.title!r}")
            title = focus.window_title(hwnd) or self.title
            try:
                frame = capture_client_printwindow(hwnd)
                method = "PrintWindow"
            except Exception:
                frame = capture_client(hwnd)
                method = "BitBlt"
        else:
            hwnd = focus.find_window(self.title)
            title = (focus.window_title(hwnd) if hwnd else "") or self.title

        # Optional downscale BEFORE OCR -- OCR cost scales with pixel count, and the
        # V2/focus logic is normalized so it is resolution-independent. Big speed-up
        # for the V5 nav. Default None keeps V4 behavior (full resolution).
        if downscale_width and getattr(frame, "width", 0) > int(downscale_width):
            from v3.frame_utils import resize_frame

            frame = resize_frame(frame, max_width=int(downscale_width))
            method = f"{method}+ds{int(downscale_width)}"

        items = []
        if full_ocr:
            items = self.ocr.read_frame(frame, min_confidence=self.min_confidence)
        v3 = self.hybrid.analyze_frame(
            frame,
            ocr_items=items,
            run_full_ocr=False,
            run_region_ocr=region_ocr,
            min_confidence=self.min_confidence,
        )
        # The V1 smart detector is a slow pixel-loop; skip it when the caller does
        # not use smart_state (e.g. the V5 nav uses decide_mode3_navigation, which
        # reads only v3). Default keeps V4 behavior.
        smart = None if skip_smart else self.smart_detector.detect(frame)
        elapsed = (time.perf_counter() - start) * 1000.0
        return V4Snapshot(
            frame=frame,
            window_title=title,
            capture_method=method,
            ocr_items=items,
            v3=v3,
            smart_state=getattr(smart, "state", "") if smart is not None else "",
            smart_confidence=float(getattr(smart, "confidence", 0.0) or 0.0) if smart is not None else 0.0,
            elapsed_ms=elapsed,
        )

