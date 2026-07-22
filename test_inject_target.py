"""Behavioral check for the dictation-target fix (Bug 2): text must land where
the user originally clicked even if focus moves while Aurora is thinking.

Crux: capture_target() snapshots the focused window; restore_target() must beat
the Win32 foreground-lock and bring an arbitrary window back to the foreground
from a background thread. We snapshot window A (this console), drive focus to a
freshly-launched Notepad (window B), then assert restore_target pulls A back.

Run:  venv\\Scripts\\python.exe test_inject_target.py
"""
import ctypes
import subprocess
import time
from ctypes import wintypes

from app import context

_u32 = ctypes.windll.user32
_u32.GetForegroundWindow.restype = wintypes.HWND
_u32.IsWindowVisible.argtypes = [wintypes.HWND]
_u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

_ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _fg():
    return _u32.GetForegroundWindow()


def _find_window(title_substr: str):
    found = []

    def cb(hwnd, _lp):
        if _u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            _u32.GetWindowTextW(hwnd, buf, 256)
            if title_substr.lower() in buf.value.lower():
                found.append(hwnd)
                return False
        return True

    _u32.EnumWindows(_ENUMPROC(cb), 0)
    return found[0] if found else None


# --- plumbing smoke checks (catch ctypes/struct/handle-truncation breakage) ---
assert context.restore_target(None) is False
assert context.restore_target((0, None)) is False

token_a = context.capture_target()
assert token_a is not None and token_a[0], "no foreground window to capture"
hwnd_a = token_a[0]
assert context.restore_target(token_a) is True
print(f"[ok] captured window A hwnd={hwnd_a}")

# --- drive focus to Notepad (window B), then restore A -----------------------
np = subprocess.Popen(["notepad.exe"])
try:
    hwnd_b = None
    for _ in range(50):
        time.sleep(0.1)
        hwnd_b = _find_window("Notepad")
        if hwnd_b:
            break
    assert hwnd_b and hwnd_b != hwnd_a, "Notepad window never appeared"

    assert context.restore_target((hwnd_b, None)) is True
    time.sleep(0.2)
    assert _fg() == hwnd_b, f"could not move focus to B: fg={_fg()} wanted {hwnd_b}"
    print(f"[ok] focus moved to window B (Notepad) hwnd={hwnd_b}")

    # the money assert: the Bug 2 fix — pull focus back to the original window
    assert context.restore_target(token_a) is True
    time.sleep(0.2)
    assert _fg() == hwnd_a, f"restore failed: fg={_fg()} wanted {hwnd_a}"
    print(f"[ok] restore_target pulled focus back to A hwnd={hwnd_a}")
    print("PASS")
finally:
    np.terminate()
