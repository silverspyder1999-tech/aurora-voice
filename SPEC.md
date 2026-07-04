# Local Wispr Flow Clone — Build Spec

**Status:** Research complete, ready to build (Phase 0 not yet validated on-machine)
**Date:** 2026-07-03
**Target machine:** Personal PC — RTX 5080 (16 GB, Blackwell sm_120), Ryzen 9 9900X3D, 64 GB RAM, Windows 11 Pro

---

## 1. Goal

Build a fully-local, offline clone of **Wispr Flow** (AI voice dictation). Core loop:

> press a global hotkey → speak → local ASR transcribes → a local LLM (Ollama) cleans up/formats
> the text → the result is auto-typed into whatever app currently has focus.

No cloud. Everything on-device. Privacy is a first-class feature (and a genuine edge over the SaaS product).

**Acceptance for "base functionality done"** (measurable standard):

| # | Criterion | Bar |
|---|---|---|
| A1 | **Latency (raw mode)** | p50 ≤ 700 ms, p95 ≤ 1.5 s from hotkey-release to text visible at cursor, for a 5–10 s utterance (ASR only, no LLM) |
| A2 | **Latency (cleanup mode)** | p50 ≤ 1.2 s, p95 ≤ 2.5 s from hotkey-release to cleaned text visible at cursor, warm LLM |
| A3 | **Accuracy** | 10-phrase scripted test set transcribes with zero uncorrected word errors after cleanup (natural mic speech, quiet room) |
| A4 | **Cleanup quality** | Filler words (um/uh/like) removed, sentence punctuation + capitalization correct, wording preserved on all 10 phrases; LLM never adds preamble/commentary |
| A5 | **Works everywhere** | Injection verified in: Notepad, a browser textarea (Chrome), Windows Terminal, and one Electron app (e.g. Claude/ChatGPT desktop) |
| A6 | **Clipboard safety** | Prior clipboard contents restored after paste-injection, verified over 5 consecutive dictations |
| A7 | **Stability** | 20 consecutive dictation cycles without crash, hang, stuck hotkey state, or VRAM growth |
| A8 | **Offline** | Loopback-only: works with Wi-Fi/Ethernet disabled (after models are downloaded) |
| A9 | **Recovery** | Empty/silent recording, very long utterance (60 s), and rapid double-press all handled gracefully (no crash, sensible behavior) |

---

## 2. How Wispr Flow works (verified via deep research)

Sources: Wispr engineering blog, Baseten case study, Wikipedia, comparison blogs. Adversarially verified (24/25 claims confirmed).

- **Pipeline:** global hotkey → capture → VAD/endpointing → context-conditioned ASR → *separate* personalized LLM formatting pass → text injection. *(medium confidence — company self-reported)*
- **Latency budget:** engineered to **<700 ms** from when the user stops speaking, split **ASR <200 ms / LLM <200 ms / ~200 ms networking**. *(high confidence, stated verbatim)*. A local clone reclaims the whole 200 ms network slice → target **~500 ms**.
- **Models:** NOT stock Whisper. Fine-tuned ASR conditioned on speaker/context/history + a **fine-tuned Meta Llama** for cleanup (punctuation, capitalization, style). LLM treated as high-recall / low-precision, so it's tightly constrained.

**Takeaway:** the two-stage "ASR engine + distinct LLM cleanup pass" maps perfectly onto **local Whisper + Ollama**.

---

## 3. Recommended architecture

```
 global hotkey / push-to-talk
   → mic capture (16 kHz, sounddevice / PyAudio)
   → Silero VAD (endpoint / trim silence)
   → faster-whisper large-v3, device=cuda, compute_type=float16     [ASR]
   → Ollama llama3.2-abliterate  (filler removal, punctuation, grammar, tone)  [CLEANUP]
   → text injection into focused app:
        primary  = clipboard-paste (SendInput Ctrl+V, restore prior clipboard after ~0.4 s)
        fallback = SendInput KEYEVENTF_UNICODE
   (optional) GetForegroundWindow → per-app profile that swaps the cleanup prompt / vocab
```

---

## 4. ⚠️ Blackwell (sm_120) compatibility — the #1 risk, and the reason for Phase 0

> **VALIDATED 2026-07-03 — see `PHASE0_REPORT.md` for real numbers. Corrections to the research below:**
> 1. **int8 does NOT crash** on CT2 4.8.1 + cuBLAS 12.9 wheels + driver 610.62 — both int8 and float16 work (int8 crash was an older-stack issue).
> 2. The real Windows blocker is **missing CUDA DLLs** (`cublas64_12.dll ... cannot be loaded`); fix = `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` **plus** PATH-prepend + `ctypes.WinDLL` preload (`os.add_dll_directory` alone insufficient). Without the fix it can present as a **silent hang**.
> 3. Use `http://127.0.0.1:11434` for Ollama, never `localhost` (~2 s IPv6 penalty per request on Windows).
> 4. Measured warm pipeline: large-v3 float16 ASR 0.59 s (11.3 s audio) + llama3.2 cleanup 0.26 s ≈ **~0.9 s end-to-end** projected.

| Concern | Finding | Action |
|---|---|---|
| faster-whisper default int8 | **Crashes** on RTX 50-series: `RuntimeError: cuBLAS failed with status CUBLAS_STATUS_NOT_SUPPORTED` | Use `compute_type="float16"` |
| CTranslate2 ≥4.5 | Uses cuDNN 9 / needs CUDA ≥12.3 | If CUDA runtime DLLs aren't found at load: `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` |
| PyTorch-based engines (WhisperX, insanely-fast-whisper, NeMo/Parakeet) | Stable PyTorch lacks sm_120 ("no kernel image available", supports only up to sm_90); needs nightly cu129. Parakeet also needs ~16 GB → saturates card | **Avoid for v1** |
| Fallback ASR | whisper.cpp compiled with CUDA for sm_120 | Keep as plan B |

**VRAM sizing:** large-v3 @ int8 ≈ 2.5 GB (int8 broken on Blackwell) → @ float16 budget ~4.5–5 GB; large-v3-turbo ≈ 6–10 GB and is the accuracy leader (~8.9% WER vs Parakeet 15.7% on a like-for-like test). `llama3.2` (2.2 GB) co-resident is comfortable within 16 GB. Note ~10 GB VRAM can be ambient desktop usage when many apps are open (~6 GB free live); full 16 GB available when heavy apps closed. **Always confirm with `nvidia-smi`.**

---

## 5. Recommended stack

| Layer | Choice | Notes |
|---|---|---|
| ASR | **faster-whisper `large-v3`** (CTranslate2), `device=cuda`, `compute_type=float16` | Accuracy leader; used by nearly every mature tool. `large-v3-turbo` if you want more speed. |
| VAD / endpointing | **Silero VAD** | Proven in WhisperWriter. Modes: hold-to-talk (default), toggle, latch, hands-free. |
| Global hotkey | `boppreh/keyboard` or `global-hotkeys` + `pywin32` | Chords, PTT modes. |
| Text injection | **Clipboard-paste** (SendInput Ctrl+V) primary; `KEYEVENTF_UNICODE` fallback | MS docs bless UNICODE injection for voice input. UIPI blocks elevated windows; some games ignore synthetic keys. |
| LLM cleanup | **Ollama `llama3.2-abliterate`** (already installed) | Optionally A/B `qwen2.5:7b` for quality. Tight system prompt. |
| Language | **Python** for MVP (fastest path) | Rust/Tauri only if you want a polished native tray app from day one. |

**Cleanup system prompt (starting point):**
> "Fix punctuation, capitalization, and remove filler words (um, uh, like). Preserve the meaning and wording. Output only the corrected text — no preamble, no explanation."

---

## 6. Feature scope

- **Core dictation-anywhere** — hotkey → transcribe → inject. PTT: hold (default) / toggle / latch.
- **AI cleanup** via Ollama — filler removal, punctuation, capitalization, grammar, tone.
- **Custom vocabulary / dictionary** — bias faster-whisper via `initial_prompt` (names, jargon).
- **Voice commands** — "new paragraph" → `\n\n`, "delete that", etc., via post-processing rules.
- **Context awareness** — `GetForegroundWindow` → process name → per-app tone/vocab profile (email vs code vs chat) swapping the Ollama prompt. *No known tool ships this — differentiator.*
- **Extras worth adding (local-only advantages):** true privacy, streaming "instant mode" (partial results), code-mode dictation, snippet/macro expansion, multi-language (large-v3 is multilingual for free), undo-safe injection (stash prior clipboard).

---

## 7. Fork / reference projects

| Project | Why | Verdict |
|---|---|---|
| **drajb/whisper-local** | Already faster-whisper + Ollama on Windows | **Closest match — best base** |
| cjpais/Handy (Tauri/Rust, MIT, ~23k★) | "Most forkable"; native, GPU, Whisper+Parakeet | Would need Ollama layer added |
| savbell/whisper-writer | Python + Silero VAD + configurable Whisper | VAD / recording-modes reference |
| PinW/whisper-key-local, stha-hardik/freeflow-windows | Clean Windows hotkey + clipboard-paste injection | Copy their inject/PTT code |
| braden-w/whispering (→ EpicenterHQ/epicenter) | LLM-cleanup UX (Polish/Recipes) | Ideas only — its local-ASR support was **refuted** in verification |

---

## 8. Phased build plan

**Phase 0 — DE-RISK (do first, empirically):**
1. Fresh venv in this project dir; `pip install faster-whisper`.
2. Prove Blackwell behavior: load `device=cuda` with `compute_type="int8"` (expect cuBLAS crash) then `"float16"` (expect success). Transcribe a real speech clip (generate via Windows SAPI: `System.Speech.Synthesis.SpeechSynthesizer` → `SetOutputToWaveFile`) and confirm correct text. If int8 does NOT crash, note it.
3. Confirm `large-v3` @ float16 loads/fits; record VRAM + transcription time (RTF).
4. Confirm `ollama run llama3.2-abliterate` cleans up a messy transcript well.
→ **Deliverable:** report of actual VRAM numbers, latencies, working compute_type.

**Phase 1 — MVP (no LLM yet):** fork/adapt whisper-local. hold-hotkey → record → Silero VAD trim → faster-whisper(float16) → clipboard-paste. Goal: reliable type-anywhere dictation.

**Phase 2 — AI cleanup:** add the Ollama pass (llama3.2-abliterate default, model configurable). Tune prompt. Measure end-to-end latency vs ~500 ms target.

**Phase 3 — Power features:** custom vocabulary (`initial_prompt`), voice commands (post-proc), toggle/latch PTT, system-tray UI + config file.

**Phase 4 — Context awareness + polish:** per-app profiles, undo-safe injection, streaming "instant mode" experiment.

---

## 9. Open questions to validate empirically
1. Exact VRAM co-residency numbers for the chosen Whisper + LLM hitting the latency budget.
2. Streaming ASR latency for a true "instant mode."
3. Best local vocab-biasing approach (initial_prompt vs hotwords vs post-proc).

---

## 10. Environment snapshot (2026-07-03)

- **Ollama** 0.31.1. Models: `huihui_ai/llama3.2-abliterate:latest` (2.2 GB), `huihui_ai/qwen3-abliterated:30b-a3b`, `huihui_ai/qwen3-vl-abliterated:30b-a3b-instruct`.
- **Python** 3.11.9 + pip; `py -3.11` launcher.
- **faster-whisper** 1.2.1 + **ctranslate2** 4.8.1 verified installable (in a temp POC venv — recreate here).
- CUDA toolkit (nvcc) not on PATH — fine, prebuilt wheels used.
- GPU driver 610.62, sm_120.

---

## Conventions

- Persistent project dir (this folder). Not a temp dir.
- Windows-first: PowerShell scripts. Ship a README.
- Config-driven (single `config.toml`): hotkey, ASR model + compute_type, Ollama model, cleanup prompt, injection method, PTT mode.
- Real git repo, commit per phase.

---

**Sources:** wisprflow.ai/post/technical-challenges · baseten.co/resources/customers/wispr-flow · learn.microsoft.com (SendInput / KEYBDINPUT) · github.com/{drajb/whisper-local, cjpais/Handy, savbell/whisper-writer, PinW/whisper-key-local, stha-hardik/freeflow-windows, braden-w/whispering} · SubtitleEdit#10180 (Blackwell int8 crash) · faster-whisper/WhisperX/PyTorch sm_120 issues.
