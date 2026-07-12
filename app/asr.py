"""faster-whisper ASR wrapper. Import app.bootstrap BEFORE this module.

device modes (config [asr].device):
  "auto"  -> GPU when it has >= gpu_min_free_mib free VRAM, else CPU. The GPU
             model is loaded lazily and released the moment the GPU is busy
             (checked per-dictation AND by a background watcher every gpu_poll_s),
             so a render never loses VRAM to a whisper model sitting idle.
  "cuda"  -> always GPU (loaded lazily on first use; watcher does not touch it).
  "cpu"   -> always CPU.

Models can differ per device: [asr].model runs on GPU, [asr].cpu_model on CPU
(defaults to model). Use a lighter cpu_model (e.g. distil-large-v3) so the CPU
fallback stays snappy while the GPU keeps full large-v3 accuracy.
"""
import gc
import subprocess
import threading
import time

import numpy as np
from faster_whisper import WhisperModel


def free_vram_mib() -> int:
    """Free VRAM in MiB, or 0 if it can't be read (fail safe: assume no room)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip().splitlines()[0]
        return int(out)
    except Exception:
        return 0


class Transcriber:
    def __init__(self, cfg: dict):
        a = cfg["asr"]
        self._gpu_model = a["model"]
        self._cpu_model = a.get("cpu_model") or a["model"]
        self._compute = a["compute_type"]
        self._mode = str(a.get("device", "auto")).lower()      # auto | cuda | cpu
        self._gpu_min_free = int(a.get("gpu_min_free_mib", 4000))
        self._poll_s = float(a.get("gpu_poll_s", 4))
        self.language = a["language"] or None
        self.beam_size = a["beam_size"]
        self.vad_filter = a["vad_filter"]
        # initial_prompt biases the decoder toward your vocabulary. An explicit
        # asr.initial_prompt wins; otherwise one is built from [vocab] words.
        prompt = a["initial_prompt"]
        words = cfg.get("vocab", {}).get("words", [])
        if not prompt and words:
            prompt = "Glossary: " + ", ".join(words) + "."
        self.initial_prompt = prompt or None

        self.last_device = None
        self._lock = threading.Lock()  # serialises GPU model create/use/release
        # CPU model is the always-available fallback; GPU model is lazy.
        t0 = time.time()
        self._cpu = WhisperModel(self._cpu_model, device="cpu", compute_type=self._compute)
        self._gpu = None
        self.load_s = time.time() - t0

        if self._mode == "auto":
            threading.Thread(target=self._watch, daemon=True).start()

    def _release_gpu(self):
        if self._gpu is not None:
            self._gpu = None
            gc.collect()  # CTranslate2 frees the GPU model's VRAM on destruction

    def _watch(self):
        """Free the idle GPU model as soon as a render eats the VRAM, without
        waiting for the next dictation. Cheap: only polls nvidia-smi while a GPU
        model is actually loaded."""
        while True:
            time.sleep(self._poll_s)
            if self._mode != "auto" or self._gpu is None:
                continue
            if free_vram_mib() < self._gpu_min_free:
                with self._lock:
                    self._release_gpu()

    def _pick(self):
        """(model, device_str). auto: GPU when it has headroom, else CPU. Call
        under self._lock."""
        if self._mode == "cpu":
            return self._cpu, "cpu"
        if self._mode == "cuda":
            if self._gpu is None:
                self._gpu = WhisperModel(self._gpu_model, device="cuda", compute_type=self._compute)
            return self._gpu, "cuda"
        # auto
        if free_vram_mib() >= self._gpu_min_free:
            if self._gpu is None:
                try:
                    self._gpu = WhisperModel(self._gpu_model, device="cuda", compute_type=self._compute)
                except Exception:
                    self._gpu = None  # GPU refused (OOM/driver) -> fall through to CPU
            if self._gpu is not None:
                return self._gpu, "cuda"
        else:
            self._release_gpu()  # GPU busy (render) -> hand its VRAM back, use CPU
        return self._cpu, "cpu"

    def _run(self, model, audio) -> str:
        segments, _info = model.transcribe(
            audio,
            beam_size=self.beam_size,
            language=self.language,
            vad_filter=self.vad_filter,
            initial_prompt=self.initial_prompt,
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        """Returns (text, seconds). Audio: float32 mono at 16 kHz."""
        t0 = time.time()
        with self._lock:  # held through _run so the watcher can't free the model mid-transcribe
            model, dev = self._pick()
            try:
                text = self._run(model, audio)
            except Exception:
                # GPU faulted mid-transcription (e.g. a render grabbed VRAM). Drop
                # the GPU model and retry once on CPU so the dictation still lands.
                if dev == "cuda":
                    self._release_gpu()
                    dev = "cpu"
                    text = self._run(self._cpu, audio)
                else:
                    raise
        self.last_device = dev
        return text, time.time() - t0

    def warmup(self, sample_rate: int = 16000):
        """One dummy pass so the first real dictation isn't the cold one."""
        self.transcribe(np.zeros(sample_rate, dtype=np.float32))
