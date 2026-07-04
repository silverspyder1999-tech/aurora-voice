"""Phase 4 test: context detection, profile matching, style plumbing.

Run:  venv\\Scripts\\python.exe test_phase4.py
"""
from app import bootstrap

bootstrap.preload_cuda_dlls()

import sys  # noqa: E402

from app import cleanup, config, context  # noqa: E402
from app.main import process_text  # noqa: E402

FAIL = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAIL.append(name)


cfg = config.load()

print("1. foreground process detection")
exe = context.get_foreground_exe()
check("returns an exe name", bool(exe) and exe.endswith(".exe"), exe or "(empty)")

print("2. profile matching")
check("code profile", context.match_profile(cfg, "Code.exe")[0] == "code")
check("case-insensitive", context.match_profile(cfg, "DISCORD.EXE")[0] == "chat")
check("email profile", context.match_profile(cfg, "olk.exe")[0] == "email")
check("unknown app -> None", context.match_profile(cfg, "notepad.exe") is None)
check("empty exe -> None", context.match_profile(cfg, "") is None)

print("3. profile behavior in process_text")
cfg["cleanup"]["enabled"] = True
cleaner = cleanup.Cleaner(cfg)
cleaner.warmup()

raw = "um so we should uh refactor the parse underscore config function"
_, code_prof = context.match_profile(cfg, "Code.exe")
out, _, llm_s = process_text(raw, cleaner, cfg, code_prof)
check("code profile skips cleanup (raw passthrough)", out == raw and llm_s == 0.0,
      f"llm={llm_s:.2f}s")

_, chat_prof = context.match_profile(cfg, "Discord.exe")
out, _, llm_s = process_text("um yeah that sounds good to me lets do it", cleaner, cfg, chat_prof)
print(f"     chat  -> ({llm_s:.2f}s) {out}")
check("chat style cleans", out and "um" not in out.lower().split())

_, email_prof = context.match_profile(cfg, "olk.exe")
out, _, llm_s = process_text(
    "um hey can you uh send over the q three numbers when you get a chance thanks",
    cleaner, cfg, email_prof)
print(f"     email -> ({llm_s:.2f}s) {out}")
check("email style cleans", out and "um" not in out.lower().split())

out, _, llm_s = process_text("um yeah that sounds good to me", cleaner, cfg, None)
check("no profile -> default cleanup still works", out and "um" not in out.lower().split())

print()
if FAIL:
    print(f"PHASE4 TEST FAILED: {FAIL}")
    sys.exit(1)
print("PHASE4 TEST PASSED")
