"""Phase 3 test: voice commands, inline breaks, vocab biasing.

Run:  venv\\Scripts\\python.exe test_phase3.py
"""
from app import bootstrap

bootstrap.preload_cuda_dlls()

import sys  # noqa: E402

from app import asr, cleanup, commands, config  # noqa: E402
from app.main import process_text  # noqa: E402
from selftest import load_wav_as_16k_float32  # noqa: E402

FAIL = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAIL.append(name)


print("1. command parsing (pure logic)")
check("whole: delete that", commands.whole_utterance("Delete that.") == "undo")
check("whole: scratch that", commands.whole_utterance("scratch that") == "undo")
check("whole: press enter", commands.whole_utterance("Press Enter!") == "enter")
check("whole: normal text is not a command",
      commands.whole_utterance("please delete that file for me") is None)
check("inline: new paragraph",
      commands.split_inline("first point new paragraph second point")
      == ["first point", "\n\n", "second point"],
      str(commands.split_inline("first point new paragraph second point")))
check("inline: with ASR punctuation",
      commands.split_inline("First point. New paragraph. Second point.")
      == ["First point", "\n\n", "Second point."],
      str(commands.split_inline("First point. New paragraph. Second point.")))
check("inline: new line",
      commands.split_inline("item one new line item two")
      == ["item one", "\n", "item two"])
check("inline: no markers", commands.split_inline("just plain text") == ["just plain text"])

print("2. vocab biasing (ASR initial_prompt)")
cfg = config.load()
cfg["vocab"]["words"] = ["Ollama", "Wispr Flow", "faster-whisper", "RTX 5080"]
t = asr.Transcriber(cfg)
check("prompt built", t.initial_prompt == "Glossary: Ollama, Wispr Flow, faster-whisper, RTX 5080.",
      t.initial_prompt)
t.warmup()
clip = load_wav_as_16k_float32("test.wav")
text, secs = t.transcribe(clip)
print(f"     -> ({secs:.2f}s) {text}")
check("'Ollama' correctly biased", "ollama" in text.lower(), "was 'Olima'/'alama' without vocab")

print("3. process_text integration (commands + per-segment cleanup)")
cfg["cleanup"]["enabled"] = True
cleaner = cleanup.Cleaner(cfg)
cleaner.warmup()

out, action, _ = process_text("delete that", cleaner, cfg)
check("utterance command routed", action == "undo" and out is None)

raw = "so first we um fix the bug new paragraph then we uh ship the build"
out, action, llm_s = process_text(raw, cleaner, cfg)
print(f"     -> ({llm_s:.2f}s) {out!r}")
check("break survives cleanup", "\n\n" in (out or ""))
check("segments cleaned", out and "um" not in out and "uh" not in out)

print()
if FAIL:
    print(f"PHASE3 TEST FAILED: {FAIL}")
    sys.exit(1)
print("PHASE3 TEST PASSED")
