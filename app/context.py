"""Context awareness (Phase 4): which app is the user dictating into?

Captured at record START (the user's intent), matched against [profiles.*] in
config to pick a cleanup style - or skip cleanup entirely (code/terminal).
Pure ctypes; no extra dependencies.
"""
import ctypes
import os
import time
from ctypes import wintypes

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Explicit prototypes: on 64-bit, ctypes defaults HWND returns to c_int and
# truncates the pointer. Declare the handle-passing calls we use for target
# capture/restore so window handles survive round-trips.
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.SetFocus.argtypes = [wintypes.HWND]
_user32.SetFocus.restype = wintypes.HWND
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.AttachThreadInput.restype = wintypes.BOOL


def get_foreground_exe() -> str:
    """Basename of the foreground window's process, e.g. 'Code.exe'. '' on failure."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(4096)
        size = wintypes.DWORD(len(buf))
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        _kernel32.CloseHandle(h)


def match_profile(cfg: dict, exe: str) -> tuple[str, dict] | None:
    """Return (profile_name, profile_dict) for this exe, or None."""
    if not exe:
        return None
    exe_l = exe.lower()
    for name, prof in cfg.get("profiles", {}).items():
        for pattern in prof.get("match", []):
            if pattern.lower() == exe_l:
                return name, prof
    return None


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", _RECT)]


_user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUITHREADINFO)]
_user32.GetGUIThreadInfo.restype = wintypes.BOOL


def capture_target():
    """Snapshot the window + focused control the user is dictating INTO, so we
    can paste back there even if focus moves during processing. Returns an
    opaque token for restore_target(), or None if nothing is focused."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    focus = None
    tid = _user32.GetWindowThreadProcessId(hwnd, None)
    if tid:
        gi = _GUITHREADINFO()
        gi.cbSize = ctypes.sizeof(_GUITHREADINFO)
        if _user32.GetGUIThreadInfo(tid, ctypes.byref(gi)):
            focus = gi.hwndFocus or None
    return (hwnd, focus)


def restore_target(token) -> bool:
    """Bring the captured window+control back to the foreground before injection,
    so dictated text lands where the user originally clicked even if they clicked
    away while Aurora was thinking. AttachThreadInput bypasses the Win32
    foreground-lock that otherwise makes SetForegroundWindow a no-op from a
    background thread. Returns True if the target was (re)focused."""
    if not token:
        return False
    hwnd, focus = token
    if not hwnd or not _user32.IsWindow(hwnd):
        return False
    if _user32.GetForegroundWindow() == hwnd and not focus:
        return True

    cur = _kernel32.GetCurrentThreadId()
    fg = _user32.GetForegroundWindow()
    fg_tid = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
    tgt_tid = _user32.GetWindowThreadProcessId(hwnd, None)
    attached = [t for t in {fg_tid, tgt_tid} if t and t != cur]
    for t in attached:
        _user32.AttachThreadInput(cur, t, True)
    try:
        _user32.SetForegroundWindow(hwnd)
        _user32.BringWindowToTop(hwnd)
        if focus and _user32.IsWindow(focus):
            _user32.SetFocus(focus)
    finally:
        for t in attached:
            _user32.AttachThreadInput(cur, t, False)
    time.sleep(0.03)  # let the focus change settle before the paste lands
    return True
