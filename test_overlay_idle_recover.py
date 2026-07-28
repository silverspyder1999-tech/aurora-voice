"""The overlay used to lose its window while idle and never notice.

Observed live 2026-07-28: no WisprAuroraOverlay window existed, yet the render
thread was running happily and nothing was logged. Cause: while hidden the loop
takes the `continue` branch, so it never calls push() -- and push() returning
False was the ONLY health check in the design. A window destroyed while idle
(WM_CLOSE dispatched by pump() on the last fading frame, a shell restart, a
desktop switch) therefore stayed dead until the app was restarted.

This checks the idle path now notices and rebuilds.
"""
import threading
import time

from app.config import DEFAULTS
from app.overlay import Overlay
from app.ulw import LayeredWindow


def _cfg():
    c = {k: dict(v) for k, v in DEFAULTS.items()}
    c["ui"]["overlay_fps"] = 60
    return c


def test_alive_tracks_the_handle():
    w = LayeredWindow(0, 0, 64, 32)
    assert w.alive(), "a freshly created window must report alive"
    w.destroy()
    assert not w.alive(), "alive() must be False once the HWND is destroyed"
    print("[ok] alive() tracks window destruction")


def test_idle_loss_is_detected_and_rebuilt():
    ov = Overlay(_cfg(), lambda: None)
    ov.start()
    for _ in range(100):                     # let it build its window
        if getattr(ov, "win", None) is not None:
            break
        time.sleep(0.05)
    assert ov.win is not None, "overlay never created a window"
    ov.hide()
    time.sleep(0.6)                          # settle into the idle branch
    first = ov.win

    # simulate the window disappearing underneath us while idle
    first.alive = lambda: False

    rebuilt = False
    for _ in range(120):                     # 0.5s backoff + rebuild
        if ov.win is not first and ov.win is not None:
            rebuilt = True
            break
        time.sleep(0.05)
    assert rebuilt, "idle overlay did NOT rebuild after losing its window"
    assert ov.win.alive(), "rebuilt window is not alive"
    print("[ok] idle window loss detected and rebuilt")


if __name__ == "__main__":
    test_alive_tracks_the_handle()
    test_idle_loss_is_detected_and_rebuilt()
    print("\nIDLE-RECOVERY TEST PASSED")
