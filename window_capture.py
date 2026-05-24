"""In-memory Windows client-area capture.

Screenshots are returned as raw BGRA bytes and are never written to disk.
"""
import ctypes
from ctypes import wintypes


SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

HGDIOBJ = ctypes.c_void_p


def _enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, HGDIOBJ]
gdi32.SelectObject.restype = HGDIOBJ
gdi32.BitBlt.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    HGDIOBJ,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL


class Frame:
    """A top-down BGRA image captured from the game's client area."""

    def __init__(self, width, height, bgra):
        self.width = width
        self.height = height
        self.bgra = bgra

    def iter_region(self, x1, y1, x2, y2, step=6):
        left = max(0, min(self.width - 1, int(x1 * self.width)))
        right = max(left + 1, min(self.width, int(x2 * self.width)))
        top = max(0, min(self.height - 1, int(y1 * self.height)))
        bottom = max(top + 1, min(self.height, int(y2 * self.height)))
        stride = self.width * 4
        for y in range(top, bottom, step):
            row = y * stride
            for x in range(left, right, step):
                i = row + x * 4
                b = self.bgra[i]
                g = self.bgra[i + 1]
                r = self.bgra[i + 2]
                yield r, g, b

    def ratio(self, region, predicate, step=6):
        total = 0
        matched = 0
        for pixel in self.iter_region(*region, step=step):
            total += 1
            if predicate(*pixel):
                matched += 1
        if not total:
            return 0.0
        return matched / total


def _raise_last_error(name):
    raise OSError(ctypes.get_last_error(), f"{name} failed")


def capture_client(hwnd):
    """Capture the client area of hwnd into memory.

    Screen capture is preferred because DirectX games can return stale or
    desaturated frames from PrintWindow. Captures are in memory only.
    """
    try:
        return _capture_client_screen(hwnd)
    except Exception:
        return _capture_client_printwindow(hwnd)


def capture_client_printwindow(hwnd):
    """Capture the client area via PrintWindow.

    This is slower/less reliable for some DirectX content, but it is useful for
    OCR because it avoids reading text from windows that visually overlap Forza.
    """
    return _capture_client_printwindow(hwnd)


def _client_size(hwnd):
    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        _raise_last_error("GetClientRect")
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError("window client area is empty")
    return width, height


def _frame_from_bitmap(mem_dc, bitmap, width, height):
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height  # top-down
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = BI_RGB

    buf = ctypes.create_string_buffer(width * height * 4)
    lines = gdi32.GetDIBits(
        mem_dc,
        bitmap,
        0,
        height,
        buf,
        ctypes.byref(info),
        DIB_RGB_COLORS,
    )
    if lines != height:
        _raise_last_error("GetDIBits")
    return Frame(width, height, bytes(buf))


def _capture_client_printwindow(hwnd):
    width, height = _client_size(hwnd)
    window_dc = user32.GetDC(hwnd)
    if not window_dc:
        _raise_last_error("GetDC")

    mem_dc = gdi32.CreateCompatibleDC(window_dc)
    if not mem_dc:
        user32.ReleaseDC(hwnd, window_dc)
        _raise_last_error("CreateCompatibleDC")

    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    if not bitmap:
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, window_dc)
        _raise_last_error("CreateCompatibleBitmap")

    old_bitmap = gdi32.SelectObject(mem_dc, bitmap)
    try:
        flags = PW_CLIENTONLY | PW_RENDERFULLCONTENT
        if not user32.PrintWindow(hwnd, mem_dc, flags):
            _raise_last_error("PrintWindow")
        return _frame_from_bitmap(mem_dc, bitmap, width, height)
    finally:
        gdi32.SelectObject(mem_dc, old_bitmap)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, window_dc)


def _capture_client_screen(hwnd):
    """Capture the visible client area of hwnd from the screen into memory."""
    width, height = _client_size(hwnd)
    point = POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        _raise_last_error("ClientToScreen")

    screen_dc = user32.GetDC(None)
    if not screen_dc:
        _raise_last_error("GetDC")

    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    if not mem_dc:
        user32.ReleaseDC(None, screen_dc)
        _raise_last_error("CreateCompatibleDC")

    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    if not bitmap:
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
        _raise_last_error("CreateCompatibleBitmap")

    old_bitmap = gdi32.SelectObject(mem_dc, bitmap)
    try:
        if not gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, point.x, point.y, SRCCOPY):
            _raise_last_error("BitBlt")
        return _frame_from_bitmap(mem_dc, bitmap, width, height)
    finally:
        gdi32.SelectObject(mem_dc, old_bitmap)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
