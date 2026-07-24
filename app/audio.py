"""Push-to-talk microphone capture.

The input stream runs continuously (avoids ~100-200ms stream-start latency on every
press); a flag gates whether callback frames are kept. Trade-off: the mic 'in use'
indicator stays on while the app runs.
"""
import collections
import threading

import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(self, sample_rate: int = 16000, device: str = ""):
        self.sample_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._recording = False
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self.level = 0.0  # smoothed RMS 0..~1 (atomic float)
        self._viz = collections.deque(maxlen=4096)  # ~256ms rolling window for the overlay
        self._viz_lock = threading.Lock()
        self._stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=device if device else None,
            callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status):
        self._ready.set()
        mono = indata[:, 0]
        rms = float(np.sqrt(np.mean(mono * mono)))
        target = min(1.0, rms * 12.0)  # speech RMS ~0.01-0.15 -> 0..1
        # fast attack, slow decay: tracks syllables, settles gently
        k = 0.6 if target > self.level else 0.15
        self.level += (target - self.level) * k
        with self._viz_lock:
            self._viz.extend(mono)
        if self._recording:
            with self._lock:
                self._frames.append(mono.copy())

    def recent(self, n: int = 1600) -> np.ndarray:
        """Last n mono samples (float32) for the overlay visualizer."""
        with self._viz_lock:
            if not self._viz:
                return np.zeros(0, dtype=np.float32)
            arr = np.fromiter(self._viz, dtype=np.float32, count=len(self._viz))
        return arr[-n:]

    def start_stream(self, wait: bool = True, timeout: float = 5.0):
        """Start the stream; by default block until audio is actually flowing
        (device cold-start on Windows/MME can take hundreds of ms)."""
        self._stream.start()
        if wait and not self._ready.wait(timeout):
            raise RuntimeError(f"microphone produced no audio within {timeout}s")

    def begin(self):
        with self._lock:
            self._frames = []
        self._recording = True

    def snapshot(self) -> np.ndarray:
        """All audio captured so far, WITHOUT stopping recording. Used by instant
        mode to transcribe the growing buffer while the user is still speaking."""
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._frames)

    def end(self) -> np.ndarray:
        self._recording = False
        return self.snapshot()

    def close(self):
        self._recording = False
        self._stream.stop()
        self._stream.close()
