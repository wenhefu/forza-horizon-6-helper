"""Optional OCR helpers for reading Forza UI text.

OCR is intentionally optional. If the dependency is missing or fails to load,
the automation keeps using the lightweight color/layout detectors.
"""
from dataclasses import dataclass
import logging
import time

from window_capture import capture_client, capture_client_printwindow


@dataclass
class OcrItem:
    text: str
    confidence: float
    box: object
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    nx1: float = 0.0
    ny1: float = 0.0
    nx2: float = 0.0
    ny2: float = 0.0
    ncx: float = 0.0
    ncy: float = 0.0


class OcrReader:
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger("forza6helper")
        self._engine = None
        self._available = None
        self._last_error = None

    @property
    def available(self):
        if self._available is None:
            self._ensure_engine()
        return bool(self._available)

    @property
    def last_error(self):
        return self._last_error

    def _ensure_engine(self):
        if self._available is False:
            return False
        if self._engine is not None:
            return True
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception as exc:
            self._available = False
            self._last_error = str(exc)
            self.logger.info("OCR unavailable: %s", exc)
            return False
        try:
            self._engine = RapidOCR()
            self._available = True
            self.logger.info("OCR engine ready: rapidocr-onnxruntime")
            return True
        except Exception as exc:
            self._available = False
            self._last_error = str(exc)
            self.logger.exception("OCR engine failed to initialize")
            return False

    def read_window(self, hwnd, min_confidence=0.45):
        """Read game text from hwnd using PrintWindow first, then screen capture."""
        if not self._ensure_engine():
            return []
        try:
            frame = capture_client_printwindow(hwnd)
        except Exception:
            frame = capture_client(hwnd)
        return self.read_frame(frame, min_confidence=min_confidence)

    def read_frame(self, frame, min_confidence=0.45):
        if not self._ensure_engine():
            return []
        try:
            import numpy as np
        except Exception as exc:
            self._available = False
            self._last_error = str(exc)
            self.logger.info("OCR unavailable: %s", exc)
            return []

        start = time.monotonic()
        arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape((frame.height, frame.width, 4))
        bgr = arr[:, :, :3].copy()
        try:
            result, elapsed = self._engine(bgr)
        except Exception as exc:
            self._last_error = str(exc)
            self.logger.exception("OCR read failed")
            return []

        items = []
        for item in result or []:
            try:
                box, text, confidence = item
                confidence = float(confidence)
            except Exception:
                continue
            text = str(text).strip()
            if text and confidence >= min_confidence:
                x1 = y1 = x2 = y2 = cx = cy = 0.0
                try:
                    xs = [float(point[0]) for point in box]
                    ys = [float(point[1]) for point in box]
                    x1 = min(xs)
                    y1 = min(ys)
                    x2 = max(xs)
                    y2 = max(ys)
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
                except Exception:
                    pass
                width = float(frame.width or 1)
                height = float(frame.height or 1)
                items.append(
                    OcrItem(
                        text=text,
                        confidence=confidence,
                        box=box,
                        x1=x1,
                        y1=y1,
                        x2=x2,
                        y2=y2,
                        cx=cx,
                        cy=cy,
                        nx1=x1 / width,
                        ny1=y1 / height,
                        nx2=x2 / width,
                        ny2=y2 / height,
                        ncx=cx / width,
                        ncy=cy / height,
                    )
                )

        self.logger.debug(
            "OCR read items=%d wall=%.3f engine=%s",
            len(items),
            time.monotonic() - start,
            elapsed,
        )
        return items
