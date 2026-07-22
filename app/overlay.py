"""Aurora Silk voice overlay - glowing strand ribbon floating directly on the
desktop (per-pixel alpha, no box), whose shape IS the user's voice.

Pipeline per frame (~60fps):
  mic samples -> rFFT -> mel bands (85 Hz..6.5 kHz, low=left) ->
  springs with velocity (snap attack, under-damped release) ->
  spectral-flux onset detector (consonants fire a flare pulse) ->
  7 silk strands, Siri bell envelope, additive Gaussian glow ->
  premultiplied BGRA frame -> UpdateLayeredWindow.

Voice -> color: spectral centroid sets hue (amber vowels -> cyan sibilants),
noisiness drains saturation (whispers go pale). See docs/VISUAL-RESEARCH.md.
"""
import colorsys
import math
import queue
import random
import threading
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from app.ulw import LayeredWindow, ensure_dpi_aware, primary_work_area

SAMPLE_RATE = 16000


class Overlay:
    W, H = 440, 120
    SS = 2                    # supersample factor for antialiasing
    STRANDS = 7
    POINTS = 80
    BANDS = 24
    FMIN, FMAX = 85.0, 6500.0
    FFT_N = 1024

    def __init__(self, cfg: dict, wave_source):
        """wave_source: () -> np.ndarray of recent mono float32 samples @16 kHz."""
        ui = cfg["ui"]
        self.opacity = float(ui.get("overlay_opacity", 0.85))
        self.margin_bottom = int(ui.get("overlay_margin_bottom", 24))
        self.fps = int(ui.get("overlay_fps", 60))
        self._wave_source = wave_source
        self._q: queue.Queue = queue.Queue()
        self._state = "hidden"
        self._t0 = time.time()

        # spectrum state
        self._disp = np.zeros(self.BANDS)          # displayed band values 0..1
        self._vel = np.zeros(self.BANDS)           # spring velocities
        self._floor = None
        self._peak = None
        self._last_raw = None
        self._flux_hist = []
        self._last_onset_t = 0.0
        self._pulse = 0.0
        self._hue = 45.0                            # displayed hue (deg)
        self._sat = 0.55
        self._fade = 0.0

        # mel-spaced band bins (perceptual: spreads voice energy across width)
        def mel(f):
            return 2595.0 * math.log10(1.0 + f / 700.0)

        def imel(m):
            return 700.0 * (10 ** (m / 2595.0) - 1.0)

        edges = [imel(mel(self.FMIN) + (mel(self.FMAX) - mel(self.FMIN)) * i / self.BANDS)
                 for i in range(self.BANDS + 1)]
        freqs = np.fft.rfftfreq(self.FFT_N, 1.0 / SAMPLE_RATE)
        self._bins = [np.where((freqs >= lo) & (freqs < hi))[0]
                      for lo, hi in zip(edges[:-1], edges[1:])]
        self._window = np.hanning(self.FFT_N).astype(np.float32)

        rnd = random.Random(7)
        self._strands = [{"off": (s - self.STRANDS // 2) * 0.09,
                          "spd": 1.0 + s * 0.07,
                          "ph1": rnd.uniform(0, math.tau),
                          "ph2": rnd.uniform(0, math.tau)}
                         for s in range(self.STRANDS)]
        self._u = np.linspace(0.0, 1.0, self.POINTS)
        # Siri-family bell, widened: authentic (K/(K+x^K))^K crushes the outer
        # thirds, hiding low/high-frequency humps. Scale 2.0 + outer power 1.5
        # keeps ends pinched while the whole frequency axis stays readable.
        bx = (2 * self._u - 1) * 2.0
        self._bell = (4.0 / (4.0 + np.abs(bx) ** 4)) ** 1.5

        self._thread = threading.Thread(target=self._run, daemon=True, name="aurora")

    # -- public API (any thread) ------------------------------------------
    def start(self):
        self._thread.start()

    def show(self):
        self._q.put("listening")

    def processing(self):
        self._q.put("processing")

    def hide(self):
        self._q.put("hidden")

    # -- audio analysis ----------------------------------------------------
    def _analyze(self, dt: float):
        now = time.time()
        if self._state == "listening":
            x = self._wave_source()
            if x is not None and len(x) >= self.FFT_N:
                seg = x[-self.FFT_N:] * self._window
                mag = np.abs(np.fft.rfft(seg))
                raw = np.array([np.log10(mag[b].mean() + 1e-7) if len(b) else -7.0
                                for b in self._bins])
                # adaptive floor/peak -> auto-gain for any microphone
                lo, hi = raw.min(), raw.max()
                if self._floor is None:
                    self._floor, self._peak = lo, lo + 1.0
                self._floor += (lo - self._floor) * (0.05 if lo < self._floor else 0.01)
                self._peak += (hi - self._peak) * (0.30 if hi > self._peak else 0.005)
                span = max(self._peak - self._floor, 0.4)
                target = np.clip((raw - self._floor) / span, 0.0, 1.0) ** 1.4
                target = np.convolve(target, [0.25, 0.5, 0.25], mode="same")

                # spectral flux onset: energy INCREASES only, vs rolling mean
                if self._last_raw is not None:
                    flux = float(np.maximum(0.0, raw - self._last_raw).sum())
                    self._flux_hist.append(flux)
                    if len(self._flux_hist) > 45:
                        self._flux_hist.pop(0)
                    mean = sum(self._flux_hist) / len(self._flux_hist)
                    if (flux > 1.45 * mean and flux > 0.5
                            and now - self._last_onset_t > 0.15):
                        self._pulse = min(1.4, 0.5 + flux / (mean + 1e-6) * 0.25)
                        self._last_onset_t = now
                self._last_raw = raw
            else:
                target = self._disp * 0.9
        else:
            target = np.zeros(self.BANDS)           # processing/hidden: settle

        # springs: instant-ish attack, under-damped release (one soft bounce)
        up = target > self._disp
        self._disp[up] += (target[up] - self._disp[up]) * min(1.0, dt / 0.03)
        self._vel[up] = 0.0
        k, d = 90.0, 0.92 * 2.0 * math.sqrt(90.0)
        acc = k * (target - self._disp) - d * self._vel
        self._vel[~up] += acc[~up] * dt
        self._disp[~up] += self._vel[~up] * dt
        np.clip(self._disp, 0.0, 1.2, out=self._disp)

        self._pulse *= math.exp(-dt / 0.18)

        # voice color: centroid -> hue temperature, noisiness -> saturation
        s = float(self._disp.sum())
        if s > 0.02:
            w2 = self._disp ** 2                    # energy^2: dominant band owns the hue
            centroid = float((w2 * np.arange(self.BANDS)).sum()) / (float(w2.sum()) + 1e-9) / (self.BANDS - 1)
            hue_t = 35.0 + 150.0 * min(1.0, centroid * 1.6)
            m = float(self._disp.max())
            noisiness = 1.0 - (m - s / self.BANDS) / (m + 1e-6)
            sat_t = 0.30 + 0.60 * (1.0 - noisiness)
        else:
            hue_t, sat_t = 45.0, 0.45               # calm amber at rest
        self._hue += (hue_t - self._hue) * min(1.0, dt / 0.10)
        self._sat += (sat_t - self._sat) * min(1.0, dt / 0.15)

    # -- rendering ---------------------------------------------------------
    def _render(self) -> np.ndarray:
        """Premultiplied RGBA uint8 frame (straight draw -> premult -> glow add)."""
        ss = self.SS
        W, H = self.W * ss, self.H * ss
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        t = time.time() - self._t0
        mid = H / 2.0
        breath = 1.0 + 0.18 * math.sin(t * 1.1)     # never freeze
        spec = np.interp(self._u * (self.BANDS - 1), np.arange(self.BANDS), self._disp)
        amp = self._bell * (1.6 * breath + spec * (H * 0.40)) * (1.0 + 0.35 * self._pulse)
        xs = self._u * W

        light = 0.58 + 0.14 * self._pulse
        for i, s in enumerate(self._strands):
            hue = ((self._hue + i * 4.0) % 360.0) / 360.0
            r, g, b = [int(c * 255) for c in colorsys.hls_to_rgb(hue, light, self._sat)]
            ph = (np.sin(math.tau * 2.1 * self._u + t * 4.5 * s["spd"] + s["ph1"])
                  * (0.8 + s["off"])
                  + 0.3 * np.sin(math.tau * 3.4 * self._u - t * 3.0 * s["spd"] + s["ph2"]))
            ys = mid + amp * ph
            pts = list(zip(xs.tolist(), ys.tolist()))
            draw.line(pts, fill=(r, g, b, 80), width=3 * ss, joint="curve")   # halo body
            draw.line(pts, fill=(r, g, b, 235), width=ss, joint="curve")      # bright core

        # premultiply, then additive glow: blurred copy added on top (bloom)
        arr = np.asarray(img, dtype=np.uint16)
        prem = arr.copy()
        prem[..., :3] = arr[..., :3] * arr[..., 3:4] // 255
        glow = Image.fromarray(prem.astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(5 * ss))
        garr = np.asarray(glow, dtype=np.uint16)
        out = np.clip(prem + garr * (14 + int(6 * self._pulse)) // 10, 0, 255)

        frame = Image.fromarray(out.astype(np.uint8)).resize(
            (self.W, self.H), Image.LANCZOS)
        return np.asarray(frame, dtype=np.uint8)

    # -- render thread -----------------------------------------------------
    def _make_window(self) -> bool:
        """(Re)create the layered window at the current work-area bottom-center.
        Geometry is recomputed each call so a resolution/DPI change can't strand
        it off-screen after a rebuild."""
        ensure_dpi_aware()
        left, top, right, bottom = primary_work_area()
        x = left + (right - left - self.W) // 2
        y = bottom - self.H - self.margin_bottom
        self.geometry = (x, y, self.W, self.H)
        try:
            self.win = LayeredWindow(x, y, self.W, self.H)
            return True
        except Exception as e:
            print(f"[overlay] layered window create failed ({e})")
            self.win = None
            return False

    def _run(self):
        if not self._make_window():
            return

        budget = 1.0 / max(20, self.fps)
        last = time.time()
        shown = False
        self.frames = 0  # perf probe for tests
        while True:
            try:
                try:
                    while True:
                        new = self._q.get_nowait()
                        if new != "hidden" and self._state == "hidden":
                            self._floor = self._peak = None  # recalibrate mic gain
                            self._last_raw = None
                        self._state = new
                except queue.Empty:
                    pass

                now = time.time()
                dt = min(0.05, now - last)
                last = now

                # fade toward visible/hidden; actually hide window at fade 0
                target_fade = 0.0 if self._state == "hidden" else 1.0
                step = dt / (0.12 if target_fade > self._fade else 0.18)
                self._fade = min(1.0, max(0.0, self._fade + math.copysign(step, target_fade - self._fade))) \
                    if abs(target_fade - self._fade) > 1e-3 else target_fade

                if self._fade <= 0.0:
                    if shown:
                        self.win.hide()
                        shown = False
                    time.sleep(0.05)
                    continue

                self._analyze(dt)
                frame = self._render()
                self.win.push(frame, opacity=self._fade * self.opacity, premultiplied=True)
                if not shown:
                    self.win.show()
                    shown = True
                self.win.pump()
                self.frames += 1

                elapsed = time.time() - now
                if elapsed < budget:
                    time.sleep(budget - elapsed)
            except Exception as e:
                # ponytail: a transient GDI/render fault (display-mode change or a
                # GPU driver reset invalidating the layered-window DC) must NOT kill
                # this daemon thread and take the wave down until the next app
                # restart. Log, rebuild the window, and resume. Backoff avoids a
                # tight spin if the rebuild itself keeps failing.
                print(f"[overlay] render error ({type(e).__name__}: {e}); rebuilding")
                shown = False
                self._fade = 0.0
                time.sleep(0.5)
                if not self._make_window():
                    time.sleep(2.0)
                last = time.time()
