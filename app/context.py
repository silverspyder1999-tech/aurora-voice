"""Context awareness (Phase 4): which app is the user dictating into?

Captured at record START (the user's intent), matched against [profiles.*] in
config to pick a cleanup style - or skip cleanup entirely (code/terminal).
Pure ctypes; no extra dependencies.
"""
import ctypes
import os
from ctypes import wintypes

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


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
