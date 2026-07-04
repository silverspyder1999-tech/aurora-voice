"""faster-whisper ASR wrapper. Import app.bootstrap BEFORE this module."""
import time

import numpy as np
from faster_whisper import WhisperModel


class Transcriber:
    def __init__(self, cfg: dict):
        a = cfg["asr"]
        t0 = time.time()
        self.model = WhisperModel(a["model"], device="cuda", compute_type=a["compute_type"])
        self.load_s = time.time() - t0
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

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        """Returns (text, seconds). Audio: float32 mono at 16 kHz."""
        t0 = time.time()
        segments, _info = self.model.transcribe(
            audio,
            beam_size=self.beam_size,
            language=self.language,
            vad_filter=self.vad_filter,
            initial_prompt=self.initial_prompt,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, time.time() - t0

    def warmup(self, sample_rate: int = 16000):
        """One dummy pass so the first real dictation isn't the cold one."""
        self.transcribe(np.zeros(sample_rate, dtype=np.float32))
