"""Visual + perf test for the Aurora Silk overlay. Feeds synthetic audio and
screenshots the result: LOW tone humps LEFT, HIGH tone humps RIGHT, speech
dances (with onset flares), silence settles to a calm breathing line.
Also measures achieved FPS and verifies click-through window styles.

Run:  venv\\Scripts\\python.exe test_overlay.py [out_dir]
"""
import sys
import time

import numpy as np
from PIL import ImageGrab

from app import config
from app.overlay import Overlay, SAMPLE_RATE

OUT = sys.argv[1] if len(sys.argv) > 1 else "."

_mode = {"kind": "silence"}
_rng = np.random.default_rng(3)


def fake_samples():
    n = 2048
    t = np.arange(n) / SAMPLE_RATE
    kind = _mode["kind"]
    if kind == "silence":
        return (_rng.normal(0, 0.0006, n)).astype(np.float32)
    if kind == "low":
        return (0.05 * np.sin(2 * np.pi * 220 * t)
                + _rng.normal(0, 0.001, n)).astype(np.float32)
    if kind == "high":
        return (0.04 * np.sin(2 * np.pi * 3200 * t)
                + _rng.normal(0, 0.001, n)).astype(np.float32)
    # "speech": bursty broadband with syllable rhythm
    return (0.06 * np.sin(2 * np.pi * 300 * t) * np.abs(np.sin(2 * np.pi * 4 * t))
            + 0.02 * _rng.normal(0, 1, n) * (_rng.random(n) > 0.5)).astype(np.float32)


cfg = config.load()
ov = Overlay(cfg, fake_samples)
ov.start()
for _ in range(80):
    if hasattr(ov, "geometry"):
        break
    time.sleep(0.1)
x, y, w, h = ov.geometry
bbox = (x, y, x + w, y + h)
print("overlay at", bbox)

ov.show()
_mode["kind"] = "silence"; time.sleep(0.8)     # gain calibration
_mode["kind"] = "speech";  time.sleep(1.0)

# fps probe over 2s of speech
f0 = getattr(ov, "frames", 0); t0 = time.time()
time.sleep(2.0)
fps = (ov.frames - f0) / (time.time() - t0)
print(f"achieved fps: {fps:.1f}")

for kind, wait in [("low", 1.2), ("high", 1.2), ("speech", 0.9), ("silence", 1.6)]:
    _mode["kind"] = kind
    time.sleep(wait)
    ImageGrab.grab(bbox=bbox).save(f"{OUT}/aurora_{kind}.png")
    print(f"captured aurora_{kind}.png")

# click-through / no-activate styles
st = ov.win.ex_style()
need = {"LAYERED": 0x80000, "TRANSPARENT": 0x20, "NOACTIVATE": 0x8000000, "TOOLWINDOW": 0x80}
missing = [k for k, v in need.items() if not (st & v)]
print("ex-style check:", "OK (all set)" if not missing else f"MISSING {missing}")

ov.hide()
time.sleep(0.5)
ImageGrab.grab(bbox=bbox).save(f"{OUT}/aurora_hidden.png")
print("captured aurora_hidden.png (desktop only)")
print("done" if not missing and fps > 25 else "DONE WITH WARNINGS")
