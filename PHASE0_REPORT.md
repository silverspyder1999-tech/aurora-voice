# Phase 0 Report — Blackwell (RTX 5080) Validation

**Date:** 2026-07-03 · **Verdict: GO for Phase 1.** All components validated on-device.

## Environment as tested
- RTX 5080 16 GB (sm_120), driver 610.62 · Ryzen 9 9900X3D · 64 GB RAM · Windows 11 Pro
- Python 3.11.9 venv at `.\venv` · faster-whisper 1.2.1 · ctranslate2 4.8.1
- `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` pip wheels (cuBLAS 12.9 / cuDNN 9)
- Ollama 0.31.1 · `huihui_ai/llama3.2-abliterate:latest` (3B, 2.2 GB)
- Test audio: 11.3 s SAPI-generated speech (`test.wav`)

## Key findings (differences vs research predictions ⚠️)

1. ⚠️ **int8 does NOT crash on Blackwell** on this stack. The researched `cuBLAS CUBLAS_STATUS_NOT_SUPPORTED` crash (SubtitleEdit #10180 era) does not reproduce with CT2 4.8.1 + cuBLAS 12.9 wheels + driver 610.62. Both `int8` and `float16` work.
2. **The real blocker was missing CUDA runtime DLLs** — `RuntimeError: Library cublas64_12.dll is not found or cannot be loaded`. Fix (all three needed on Windows):
   - `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`
   - `os.add_dll_directory()` alone is **not** sufficient — CT2 uses plain `LoadLibrary`
   - Prepend `site-packages/nvidia/*/bin` to `PATH` **and** preload the DLLs via `ctypes.WinDLL` (see `test_asr.py` preamble)
   - Failure mode without the fix is ugly: in a non-console/buffered context it presented as a **silent hang**, not a clean exception.
3. ⚠️ **Use `127.0.0.1`, never `localhost`, for the Ollama API** on Windows: `localhost` costs ~2 s per request (IPv6 `::1` attempted first). Warm cleanup wall time: **2.33 s → 0.26 s** (9×).

## Measurements

### ASR — faster-whisper, beam_size=5, 11.3 s audio
| Model | compute | Load | Cold | Warm | RTF (warm) | Transcript quality |
|---|---|---|---|---|---|---|
| small | int8 | 1.06 s | 0.79 s | **0.28 s** | 0.025 | "RTX 5000-80", "olima" |
| small | float16 | 1.03 s | 1.52 s | 1.30 s | 0.116 | same errors |
| **large-v3** | **int8** | ~2–3 s* | 0.85 s | **0.66 s** | 0.059 | **"RTX 5080" correct**; "Olima" |
| **large-v3** | **float16** | 2.52 s | 0.67 s | **0.59 s** | 0.053 | **"RTX 5080" correct**; "Olima" |

\* int8 "load 46.5 s" included the one-time ~3 GB HuggingFace download.

- "Olima"→"Ollama" is a custom-vocabulary case (Phase 3 `initial_prompt`), exactly as planned.
- large-v3 warm ≈ **0.6 s for 11.3 s of audio**; shorter utterances will be faster.

### LLM cleanup — Ollama llama3.2-abliterate (3B), 232-char messy transcript
| State | Wall | GPU eval | Throughput |
|---|---|---|---|
| Cold (model load) | 7.05 s | 0.14 s | — |
| Warm, via `localhost` | 2.33 s | 0.12 s | 300 tok/s |
| **Warm, via `127.0.0.1`** | **0.26 s** | 0.13 s | ~300 tok/s |

Quality: fillers removed, punctuation/caps correct. Slightly over-paraphrases ("get feedback from sarah" → "receive Sarah's feedback") — Phase 2 prompt-tuning item.

### VRAM co-residency (implicitly tested)
During the large-v3 float16 run, **llama3.2 was still resident in Ollama** (5 min keep_alive) alongside ~7–10 GB of desktop ambient: peak 15.7 / 16 GB, minimum free 237 MB — tight but functional, and both models performed normally. With ambient closed there is comfortable headroom. `large-v3-turbo` and int8 are the pressure-relief options.

## Projected end-to-end latency (warm pipeline)
ASR ~0.6 s + cleanup ~0.26 s + injection ~0.1 s ≈ **~0.9–1.0 s** for a 10 s utterance — within the A2 acceptance bar (p50 ≤ 1.2 s). Shorter utterances and/or `large-v3-turbo` should approach ~0.5 s.

## Decisions for Phase 1
- **ASR default: `large-v3`, `compute_type=float16`** (best measured accuracy+speed; int8 kept as low-VRAM config option since it also works).
- Ship the **DLL preload preamble** in the app bootstrap.
- **Ollama via `http://127.0.0.1:11434`** with `keep_alive` to hold the model warm.
- Make model/compute/keep_alive configurable in `config.toml`; benchmark `large-v3-turbo` as a follow-up.
