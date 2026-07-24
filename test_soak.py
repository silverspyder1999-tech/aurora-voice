"""A7 stability soak: drive the ASR+cleanup pipeline N cycles, watch for
crashes, output drift, latency runaway, and VRAM leak.

Run:  venv\\Scripts\\python.exe test_soak.py [cycles]   (default 20)

Covers the headless half of acceptance item A7. The GUI/inject/overlay half is
covered by test_inject_target.py + test_overlay_recover.py.
"""
import subprocess
import sys
import time
import wave

from app import bootstrap

bootstrap.preload_cuda_dlls()

import numpy as np  # noqa: E402

from app import asr, cleanup, config  # noqa: E402

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 20
STALL_CEILING_S = 8.0   # a healthy cycle is ~1s warm; CPU-gate fallback ~5s; >8s = a real hang
LEAK_CEILING_MB = 600   # generous: other processes share the GPU, so this is a smoke signal


def load_wav_16k(path):
    with wave.open(path, "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            data = data.reshape(-1, 2).mean(axis=1)
    if sr != 16000:
        data = np.interp(np.linspace(0, 1, int(len(data) * 16000 / sr)),
                         np.linspace(0, 1, len(data)), data).astype(np.float32)
    return data


def gpu_used_mb():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


def main():
    cfg = config.load()
    t = asr.Transcriber(cfg)
    t.warmup()
    cleaner = cleanup.Cleaner(cfg)
    cleaner.warmup()
    clip = load_wav_16k("test.wav")

    vram0 = gpu_used_mb()
    lat, fails = [], []
    print(f"A7 soak: {CYCLES} cycles through ASR+cleanup (start VRAM {vram0} MiB)")
    for i in range(1, CYCLES + 1):
        c0 = time.time()
        try:
            text, asr_s = t.transcribe(clip)
            cleaned, llm_s, used = cleaner.clean(text)
        except Exception as e:
            fails.append(f"cycle {i}: EXCEPTION {e!r}")
            continue
        took = time.time() - c0
        lat.append(took)
        if "quick brown fox" not in text.lower():
            fails.append(f"cycle {i}: ASR drift -> {text!r}")
        if not cleaned:
            fails.append(f"cycle {i}: cleanup returned empty")
        if took > STALL_CEILING_S:
            fails.append(f"cycle {i}: stall {took:.1f}s (> {STALL_CEILING_S}s)")
        if i % 5 == 0 or i == CYCLES:
            print(f"  [{i:>2}/{CYCLES}] {took:.2f}s (asr {asr_s:.2f} llm {llm_s:.2f} used={used}) "
                  f"VRAM {gpu_used_mb()} MiB")

    vram1 = gpu_used_mb()
    lat.sort()
    p50 = lat[len(lat) // 2] if lat else 0
    p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else 0
    leak = (vram1 - vram0) if (vram0 is not None and vram1 is not None) else None
    print(f"\nlatency  p50 {p50:.2f}s  p95 {p95:.2f}s  max {lat[-1]:.2f}s" if lat else "no cycles ran")
    print(f"VRAM     {vram0} -> {vram1} MiB  (delta {leak} MiB)")

    if leak is not None and leak > LEAK_CEILING_MB:
        fails.append(f"VRAM grew {leak} MiB over {CYCLES} cycles (> {LEAK_CEILING_MB}) - possible leak")

    if fails:
        print("\nSOAK FAILED:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print(f"\nSOAK PASSED: {CYCLES}/{CYCLES} cycles clean, no drift, no stall, no leak")


if __name__ == "__main__":
    main()
