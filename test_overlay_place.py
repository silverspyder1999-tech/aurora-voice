"""Unit test: overlay.place() anchors near a point and stays on-screen; and the
caret locator returns a sane value. No window/thread started.

Run:  venv\\Scripts\\python.exe test_overlay_place.py
"""
from app import context
from app.config import load
from app.overlay import Overlay
from app.ulw import primary_work_area, ensure_dpi_aware

ensure_dpi_aware()
ov = Overlay(load(), lambda: None)   # __init__ only; no start()
L, T, R, B = primary_work_area()
W, H = ov.W, ov.H
FAIL = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAIL.append(name)


def place(cx, cy):
    ov.place(cx, cy)
    return ov._pending_pos


# centered horizontally and on-screen for a comfortable interior point
x, y = place((L + R) // 2, (T + B) // 2)
check("stays on screen", L <= x <= R - W and T <= y <= H + T or T <= y <= B - H, f"({x},{y})")
check("centered on cx", abs((x + W // 2) - (L + R) // 2) <= 1, f"x={x}")
check("below the point", y > (T + B) // 2, f"y={y} vs cy={(T + B) // 2}")

# left edge clamps to the work-area left
x, _ = place(L - 50, (T + B) // 2)
check("clamps at left", x == L, f"x={x}")

# right edge clamps so the whole window fits
x, _ = place(R + 50, (T + B) // 2)
check("clamps at right", x == R - W, f"x={x}")

# a point near the very bottom flips the ribbon ABOVE it (never off-screen)
x, y = place((L + R) // 2, B - 5)
check("flips above near bottom", T <= y <= B - H, f"y={y}")

# caret locator must not crash and returns None or a 4-int tuple
r = context.caret_screen_rect()
check("caret locator sane", r is None or (len(r) == 4 and all(isinstance(v, int) for v in r)), repr(r))

print("\nPLACE TEST " + ("PASSED" if not FAIL else f"FAILED: {FAIL}"))
assert not FAIL
