"""Per-pixel-alpha overlay window via Win32 UpdateLayeredWindow (pure ctypes).

Why: tkinter can only chroma-key (no real transparency, no glow). A layered
window takes a premultiplied BGRA bitmap each frame and composites it onto the
desktop atomically - true per-pixel alpha, no flicker, no window box.

Rules baked in (see docs/VISUAL-RESEARCH.md):
- premultiply RGB by alpha or glow edges fringe
- never mix SetLayeredWindowAttributes with UpdateLayeredWindow
- set DPI awareness BEFORE window creation
- WS_EX_TRANSPARENT + NOACTIVATE: click-through, can never steal focus
"""
import ctypes
from ctypes import wintypes

import numpy as np

_u32 = ctypes.windll.user32
_g32 = ctypes.windll.gdi32

# explicit prototype: without it ctypes guesses c_int and 64-bit LPARAM overflows
_u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]
_u32.DefWindowProcW.restype = ctypes.c_ssize_t

WS_POPUP = 0x80000000
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x08000000, 0x00000080, 0x00000008
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 2, 0, 1
BI_RGB, DIB_RGB_COLORS = 0, 0

_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_byte)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


def ensure_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            _u32.SetProcessDPIAware()
        except Exception:
            pass


def primary_work_area() -> tuple[int, int, int, int]:
    rect = (ctypes.c_int * 4)()
    _u32.SystemParametersInfoW(0x0030, 0, rect, 0)  # SPI_GETWORKAREA
    return rect[0], rect[1], rect[2], rect[3]


class LayeredWindow:
    """A topmost, click-through, never-activating layered window that displays
    a numpy RGBA frame (straight alpha, uint8, shape HxWx4) per push()."""

    _class_registered = False
    _wndproc_ref = None  # keep callback alive

    def __init__(self, x: int, y: int, w: int, h: int):
        self.w, self.h = w, h
        self.x, self.y = x, y
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)

        if not LayeredWindow._class_registered:
            LayeredWindow._wndproc_ref = _WNDPROC(
                lambda hw, msg, wp, lp: _u32.DefWindowProcW(hw, msg, wp, lp))
            wc = _WNDCLASSW()
            wc.lpfnWndProc = LayeredWindow._wndproc_ref
            wc.hInstance = hinst
            wc.lpszClassName = "WisprAuroraOverlay"
            if not _u32.RegisterClassW(ctypes.byref(wc)):
                if ctypes.GetLastError() != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                    raise ctypes.WinError()
            LayeredWindow._class_registered = True

        ex = (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
              | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
        self.hwnd = _u32.CreateWindowExW(ex, "WisprAuroraOverlay", "wispr-aurora",
                                         WS_POPUP, x, y, w, h, None, None, hinst, None)
        if not self.hwnd:
            raise ctypes.WinError()

        # one reusable top-down 32-bit DIB section; we memmove pixels into it
        self._screen_dc = _u32.GetDC(None)
        self._mem_dc = _g32.CreateCompatibleDC(self._screen_dc)
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, -h
        bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, BI_RGB
        self._bits = ctypes.c_void_p()
        self._dib = _g32.CreateDIBSection(self._mem_dc, ctypes.byref(bmi),
                                          DIB_RGB_COLORS, ctypes.byref(self._bits),
                                          None, 0)
        if not self._dib:
            raise ctypes.WinError()
        _g32.SelectObject(self._mem_dc, self._dib)

    def push(self, rgba: np.ndarray, opacity: float = 1.0, premultiplied: bool = False) -> bool:
        """Composite an RGBA uint8 frame onto the desktop. Pass premultiplied=True
        if RGB is already multiplied by alpha (correct for blurred/composited art).
        Returns False if UpdateLayeredWindow failed - it does NOT raise, so the
        caller must check: a stale screen DC (display-mode change, GPU reset, or
        return from the lock/secure desktop) makes it silently no-op forever, and
        the only fix is to rebuild the window + DCs."""
        if premultiplied:
            prem = rgba[..., :3]
        else:
            a = rgba[..., 3:4].astype(np.uint16)
            prem = ((rgba[..., :3].astype(np.uint16) * a) // 255).astype(np.uint8)
        bgra = np.empty((self.h, self.w, 4), dtype=np.uint8)
        bgra[..., 0], bgra[..., 1], bgra[..., 2] = prem[..., 2], prem[..., 1], prem[..., 0]
        bgra[..., 3] = rgba[..., 3]
        buf = np.ascontiguousarray(bgra)
        ctypes.memmove(self._bits, buf.ctypes.data, buf.nbytes)

        blend = _BLENDFUNCTION(AC_SRC_OVER, 0, max(0, min(255, int(opacity * 255))),
                               AC_SRC_ALPHA)
        pos, size = _POINT(self.x, self.y), _SIZE(self.w, self.h)
        src = _POINT(0, 0)
        ok = _u32.UpdateLayeredWindow(self.hwnd, self._screen_dc, ctypes.byref(pos),
                                      ctypes.byref(size), self._mem_dc, ctypes.byref(src),
                                      0, ctypes.byref(blend), ULW_ALPHA)
        return bool(ok)

    def show(self):
        _u32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def hide(self):
        _u32.ShowWindow(self.hwnd, SW_HIDE)

    def destroy(self):
        """Release GDI resources + the window so a rebuild starts clean. Must run
        on the owning thread (the render thread that created it)."""
        for attr, freer in (("_dib", _g32.DeleteObject),
                            ("_mem_dc", _g32.DeleteDC)):
            h = getattr(self, attr, None)
            if h:
                try:
                    freer(h)
                except Exception:
                    pass
                setattr(self, attr, None)
        if getattr(self, "_screen_dc", None):
            try:
                _u32.ReleaseDC(None, self._screen_dc)
            except Exception:
                pass
            self._screen_dc = None
        if getattr(self, "hwnd", None):
            try:
                _u32.DestroyWindow(self.hwnd)
            except Exception:
                pass
            self.hwnd = None

    def pump(self):
        """Drain pending window messages (call each frame from the owner thread)."""
        msg = wintypes.MSG()
        while _u32.PeekMessageW(ctypes.byref(msg), self.hwnd, 0, 0, 1):  # PM_REMOVE
            _u32.TranslateMessage(ctypes.byref(msg))
            _u32.DispatchMessageW(ctypes.byref(msg))

    def ex_style(self) -> int:
        return _u32.GetWindowLongPtrW(self.hwnd, -20)  # GWL_EXSTYLE
