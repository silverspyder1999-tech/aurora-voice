# Voice-Wave Visual Upgrade — Research Notes (2026-07-03)

(Design research distilled from teardowns of Siri, ChatGPT voice, Google Assistant, and
creative-coding sources; informed the Aurora Silk overlay implementation.)

## Design principles (from Siri / ChatGPT orb / Google / Wispr teardowns)
1. State is the product; amplitude is the garnish — express idle → listening → hearing-you → thinking via *shape change*.
2. Envelope the wave: Siri's bell attenuation `g(x) = (K/(K+x^K))^K` (K=4) pins ends to zero → reads as breathing, not oscilloscope.
3. Never fully freeze — idle = slow noise-driven breath (the core "alive" trick in every orb).
4. Additive glow = premium: layered translucent curves with additive blending bloom brighter where they overlap (Siri's "fluorescent" look).
5. Visual must move within ~50–100 ms of voice onset; latency breaks the illusion faster than any styling flaw.
6. Dictation tools win by near-invisibility (Wispr ships a 20–100% opacity slider) — keep ours configurable.
7. Best visualizers carry information: pitch→hue, noisiness→saturation (voiced=colorful, whisper=pale), semantic color (Google Recorder).

## Technique pipeline (shared by every polished visualizer)
FFT (2048) → **mel-scale bands** (`mel = 2595·log10(1+f/700)`, 24 bands 85–6500 Hz)
→ **spring smoothing** per band (fast attack ~30 ms; release = slightly under-damped spring ~0.9× critical for one soft overshoot bounce)
→ parallel **spectral-flux onset detector** (half-wave-rectified frame diff vs 1.3–1.6× rolling mean, 100–250 ms hold)
→ continuous values drive geometry/color/glow; **onset events** drive discrete pulses/bursts/flares (12% scale pop, ~180 ms exponential release).

Color mapping: energy→brightness (fastest perceptual channel), spectral centroid→temperature (amber↔cyan), noisiness→saturation.

2D glow without shaders: additive blending; multi-pass stroke (widths 16/8/4/1.5 @ alpha .05/.1/.2/1); pre-rendered radial-gradient sprites (~10× faster than shadowBlur); trail persistence via destination-out fade (never low-alpha black fills — gray remnants).

## Renderer upgrade path (to escape tkinter's ceiling)
**Recommended: Win32 `UpdateLayeredWindow` + Pillow/numpy** — true per-pixel alpha (no pill box, no chroma key), Gaussian glow, flicker-free (atomic blit, no WM_PAINT), 60 fps at 400×120 ≈ 2–5 ms/frame CPU, ~200 lines of ctypes, zero heavy deps.
Gotchas: premultiply alpha (`rgb·a/255`) or glow edges fringe; never mix SetLayeredWindowAttributes with ULW; set per-monitor-v2 DPI awareness before window creation; alpha=0 pixels are already mouse-transparent, `WS_EX_TRANSPARENT` for whole-window pass-through; show with SW_SHOWNOACTIVATE.
Runner-up: PyQt6 (same mechanism under the hood, richer API, ~100 MB dep). WebView2: blocked (click-through unsolved). Direct2D via Python: not worth it.

## Concepts (see artifact for live demos)
1. **Aurora Silk** (recommended) — current strand ribbon, unboxed: per-pixel-alpha glow floating on desktop; centroid→hue, whisper→pale, onset→flare+whip. Evolves existing identity.
2. **Ember Field** — mirrored spine + onset-burst particles that drift/die over seconds ("voice leaves consequences").
3. **Plasma Orb** — compact noise-displaced breathing orb (ChatGPT-style), never repeats/never stops.
4. **Comet Ticker** — scrolling mirrored voiceprint history, hue = centroid per moment.

Shared animation brain (mel bands → springs → flux onsets) works for all four → ship one, keep others as themes.

Full agent findings with source URLs live in the session transcript (2026-07-03); key sources: craigdehner.com/siri, SiriWaveJS math writeup, wisprflow.ai design post, audioMotion-analyzer, theorangeduck spring-roll-call, Parallelcube beat detection, SoundCloud waveform blog, duckmaestro per-pixel alpha, transparent-overlay (GitHub), Qt qwindowswindow.cpp.
