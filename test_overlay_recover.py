"""Detection check for the stale-DC fix: push() must return False when
UpdateLayeredWindow fails, so the overlay loop rebuilds instead of leaving a
visible-but-blank window (the recurring 'ribbon gone' bug).

Run:  venv\\Scripts\\python.exe test_overlay_recover.py
"""
import ctypes

import numpy as np

from app.ulw import LayeredWindow, ensure_dpi_aware

ensure_dpi_aware()
w = LayeredWindow(10, 10, 40, 40)
frame = np.zeros((40, 40, 4), dtype=np.uint8)
frame[..., 1] = 200  # green
frame[..., 3] = 255  # opaque
assert w.push(frame) is True, "a valid push should report success"
print("[ok] valid push -> True")

# invalidate the window handle so UpdateLayeredWindow fails (simulates the
# stale-DC/dead-surface state that used to blank the ribbon silently)
ctypes.windll.user32.DestroyWindow(w.hwnd)
assert w.push(frame) is False, "push on a dead surface must report failure"
print("[ok] failed push -> False (loop will rebuild)")
print("PASS")
