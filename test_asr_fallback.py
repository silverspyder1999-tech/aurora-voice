"""GPU load must never sit inside a dictation, and a failed load must back off.

Regression for the 2026-07-31 latency bug: a poisoned CUDA context made
WhisperModel(device="cuda") fail on every _pick(), silently, ~6s per utterance.
"""
import time

import numpy as np

import app.asr as asr


class FakeModel:
    cuda_attempts = 0

    def __init__(self, name, device="cpu", **kw):
        if device == "cuda":
            FakeModel.cuda_attempts += 1
            time.sleep(0.05)
            raise RuntimeError("CUDA failed with error unknown error")

    def transcribe(self, audio, **kw):
        return iter([]), None


def main():
    asr.WhisperModel = FakeModel
    asr.free_vram_mib = lambda: 99999
    cfg = {"asr": {"model": "large-v3", "cpu_model": "distil-large-v3",
                   "compute_type": "int8", "device": "auto", "language": "en",
                   "beam_size": 1, "vad_filter": False, "initial_prompt": "",
                   "gpu_poll_s": 999}}
    t = asr.Transcriber(cfg)
    audio = np.zeros(16000, dtype=np.float32)

    t0 = time.time()
    t.transcribe(audio)
    assert time.time() - t0 < 1.0, "dictation waited on a GPU load"
    assert t.last_device == "cpu"
    time.sleep(0.3)  # let the background load fail
    assert FakeModel.cuda_attempts == 1, FakeModel.cuda_attempts

    t.transcribe(audio)
    t.transcribe(audio)
    time.sleep(0.3)
    assert FakeModel.cuda_attempts == 1, "retried a doomed GPU load inside backoff"
    assert t._gpu_retry_at > time.time(), "no backoff set after failed load"

    t._gpu_retry_at = 0.0  # backoff expired -> exactly one new attempt
    t.transcribe(audio)
    time.sleep(0.3)
    assert FakeModel.cuda_attempts == 2, FakeModel.cuda_attempts
    print("test_asr_fallback: all checks passed")


if __name__ == "__main__":
    main()
