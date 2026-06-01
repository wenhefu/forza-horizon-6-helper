"""Resize the Forza game window to a standard 16:9 client size.

Pure Win32 via ctypes -- no process injection, no API hooking, no fake focus and
no game-file modification. Resizing a top-level window with ``SetWindowPos`` is
the same OS operation as dragging the window border or using a window-snap
shortcut; with ``SWP_NOACTIVATE`` it does not even steal focus. It stays inside
the project's safety boundary.

Why this matters: the buy phase and the farm's smart-hint fallback still partly
rely on V1's *fixed-fraction* detector, which assumes a ~16:9 frame. On an
ultrawide (带鱼屏) monitor a full-screen game frame is 21:9 and those fixed
fractions point at the wrong pixels -- the exact reason V1 broke on a friend's
machine. Forcing the game's CLIENT (render) area to a known 16:9 size normalizes
the aspect ratio on any monitor, so the fixed-fraction detection behaves the same
everywhere. The game must be in windowed/borderless mode (not fullscreen
exclusive) for an external resize to take effect.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32

# 16:9 client/render presets. Any 16:9 size makes the fixed-fraction detection
# consistent; pick the largest that comfortably fits the target monitor.
PRESETS_16_9: dict[str, tuple[int, int]] = {
    "1280x720": (1280, 720),
    "1600x900": (1600, 900),
    "1920x1080": (1920, 1080),
}
# Default to 1920x1080: larger frames make the recognition (esp. the free-roam vs
# race_hud and car-grid vs eventlab distinctions) far more reliable. The user found
# 1600x900 caused mis-reads while 1920x1080 ran clean. Smaller presets stay
# available for screens that can't fit 1080p.
DEFAULT_PRESET = "1920x1080"

# SetWindowPos flags: keep Z-order and focus untouched, only move/resize.
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_GWL_STYLE = -16
_WS_THICKFRAME = 0x00040000
_WS_CAPTION = 0x00C00000


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    left: int
    top: int
    win_w: int
    win_h: int
    client_w: int
    client_h: int

    @property
    def aspect(self) -> float:
        return self.client_w / self.client_h if self.client_h else 0.0

    @property
    def resizable(self) -> bool:
        style = user32.GetWindowLongW(wintypes.HWND(self.hwnd), _GWL_STYLE)
        return bool(style & _WS_THICKFRAME) and bool(style & _WS_CAPTION)


def client_to_window_size(
    win_w: int, win_h: int, client_w: int, client_h: int, target_cw: int, target_ch: int
) -> tuple[int, int]:
    """Window (outer) size needed so the CLIENT area becomes target_cw x target_ch.

    The non-client decorations (title bar + borders) are a constant delta for a
    given window style, so we just preserve ``window - client``. Pure arithmetic
    on purpose: this is the one piece worth unit-testing without a live window.
    """
    dw = max(0, win_w - client_w)
    dh = max(0, win_h - client_h)
    return target_cw + dw, target_ch + dh


def _title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def find_game_window(title_substr: str = "Forza Horizon") -> int:
    """Return the HWND of the first visible window whose title contains
    ``title_substr`` (case-insensitive), or 0 if none. Matches the game, not our
    own helper GUI (its title has no "Forza")."""
    needle = title_substr.casefold()
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and needle in _title(hwnd).casefold():
            found.append(int(hwnd))
            return False  # stop enumeration at the first match
        return True

    user32.EnumWindows(_cb, 0)
    return found[0] if found else 0


def get_window_info(hwnd: int) -> WindowInfo:
    wr, cr = _RECT(), _RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(wr))
    user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(cr))
    return WindowInfo(
        hwnd=hwnd,
        title=_title(hwnd),
        left=wr.left,
        top=wr.top,
        win_w=wr.right - wr.left,
        win_h=wr.bottom - wr.top,
        client_w=cr.right - cr.left,
        client_h=cr.bottom - cr.top,
    )


def resize_to_16_9(title_substr: str = "Forza Horizon", preset: str = DEFAULT_PRESET) -> tuple[bool, str]:
    """Resize the game window so its client area becomes the chosen 16:9 preset.

    Returns ``(ok, human_message)``. Never raises for the expected failures
    (window not found / not resizable / resize ignored) -- it reports them so the
    GUI can show a clear line.
    """
    target_cw, target_ch = PRESETS_16_9.get(preset, PRESETS_16_9[DEFAULT_PRESET])
    hwnd = find_game_window(title_substr)
    if not hwnd:
        return False, f"没找到标题含“{title_substr}”的窗口；请先把游戏打开并切到窗口模式。"

    before = get_window_info(hwnd)
    if not before.resizable:
        return (
            False,
            f"找到游戏窗口（{before.win_w}x{before.win_h}）但它不可调整（可能是全屏独占）。"
            "请在游戏画面设置里改成“窗口”或“无边框窗口”模式后再试。",
        )

    win_w, win_h = client_to_window_size(
        before.win_w, before.win_h, before.client_w, before.client_h, target_cw, target_ch
    )
    # Keep the current top-left so the title bar never lands off-screen (safe on
    # multi-monitor too); the window simply grows toward the bottom-right.
    user32.SetWindowPos(
        wintypes.HWND(hwnd), None, before.left, before.top, win_w, win_h,
        _SWP_NOZORDER | _SWP_NOACTIVATE,
    )

    after = get_window_info(hwnd)
    ok = abs(after.client_w - target_cw) <= 2 and abs(after.client_h - target_ch) <= 2
    if ok:
        return True, (
            f"已把游戏窗口客户区从 {before.client_w}x{before.client_h}"
            f"（{before.aspect:.3f}）调成 {after.client_w}x{after.client_h}（16:9）。"
        )
    return False, (
        f"已尝试调整，但游戏把客户区保持在 {after.client_w}x{after.client_h}"
        f"（{after.aspect:.3f}）。多半是全屏独占或游戏锁定了分辨率；"
        "请在游戏里改成窗口/无边框模式后再试。"
    )
