"""Headless self-test: everything except live mic speech and live Ctrl+V.

Run:  venv\\Scripts\\python.exe selftest.py
"""
import sys
import time
import wave

from app import bootstrap

bootstrap.preload_cuda_dlls()

import numpy as np  # noqa: E402

from app import asr, audio, config  # noqa: E402
from app.inject import _get_clipboard_text, _set_clipboard_text  # noqa: E402

FAIL = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAIL.append(name)


def load_wav_as_16k_float32(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            data = data.reshape(-1, 2).mean(axis=1)
    if sr != 16000:
        x_old = np.linspace(0, 1, len(data))
        x_new = np.linspace(0, 1, int(len(data) * 16000 / sr))
        data = np.interp(x_new, x_old, data).astype(np.float32)
    return data


def main():
    print("1. config")
    cfg = config.load()
    check("config loads", isinstance(cfg, dict) and cfg["asr"]["model"], cfg["asr"]["model"])

    print("2. ASR (loads model, transcribes test.wav through the app wrapper)")
    t = asr.Transcriber(cfg)
    check("model load", True, f"{t.load_s:.1f}s")
    t.warmup()
    clip = load_wav_as_16k_float32("test.wav")
    text, secs = t.transcribe(clip)
    print(f"     -> ({secs:.2f}s) {text}")
    check("transcription", "quick brown fox" in text.lower(), f"{secs:.2f}s")

    print("3. clipboard round-trip")
    prior = _get_clipboard_text()
    marker = f"aurora-selftest-{int(time.time())}"
    ok = _set_clipboard_text(marker) and _get_clipboard_text() == marker
    if prior is not None:
        _set_clipboard_text(prior)
    restored = (_get_clipboard_text() == prior) if prior is not None else True
    check("set+read", ok)
    check("restore", restored)

    print("4. microphone stream")
    try:
        rec = audio.Recorder(cfg["audio"]["sample_rate"], cfg["audio"]["device"])
        rec.start_stream()
        rec.begin()
        time.sleep(0.5)
        captured = rec.end()
        rec.close()
        check("mic capture", len(captured) > 4000, f"{len(captured)} samples in 0.5s")
    except Exception as e:
        check("mic capture", False, str(e))

    print()
    if FAIL:
        print(f"SELFTEST FAILED: {FAIL}")
        sys.exit(1)
    print("SELFTEST PASSED")


if __name__ == "__main__":
    main()
