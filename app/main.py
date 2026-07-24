"""Aurora Voice: hold (or toggle) a hotkey -> speak -> text appears at your cursor.

Run:  venv\\Scripts\\python.exe -m app.main
"""
import ctypes
import os
import queue
import sys
import threading
import time
import winsound
from pathlib import Path

from app import bootstrap

bootstrap.preload_cuda_dlls()  # must precede faster_whisper import (app.asr)

import keyboard  # noqa: E402

from app import asr, audio, cleanup, commands, config, context, inject  # noqa: E402


def _setup_headless_logging():
    """Under pythonw.exe (autostart, no console) stdout/stderr are None and
    print() would crash the app. Log to aurora.log in the project dir instead."""
    if sys.stdout is None or sys.stderr is None:
        log_path = Path(__file__).resolve().parent.parent / "aurora.log"
        f = open(log_path, "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = f
        print(f"[aurora-voice] headless start {time.strftime('%Y-%m-%d %H:%M:%S')}")


def _single_instance() -> bool:
    """Named mutex so autostart + a manual launch can't both hook F9
    (two instances would double-paste every dictation). use_last_error is
    required: reading ERROR_ALREADY_EXISTS through windll.GetLastError() is racy
    and let two simultaneous logon launches BOTH slip through (observed: a venv
    and a system-Python copy running at once)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW(None, False, "Global\\aurora-voice-singleton")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def beep(cfg, freq, ms=80):
    if cfg["ui"]["sounds"]:
        try:
            winsound.Beep(freq, ms)
        except RuntimeError:
            pass


def process_text(raw: str, cleaner, cfg,
                 profile: dict | None = None) -> tuple[str | None, str | None, float]:
    """Turn a raw transcript into (final_text, action, llm_seconds).

    action is set (and text None) when the whole utterance was a command.
    Inline break markers are split out BEFORE cleanup so the LLM can't eat them.
    profile (Phase 4) can disable cleanup or set a style for the target app.
    """
    if cfg["commands"]["enabled"]:
        action = commands.whole_utterance(raw)
        if action:
            return None, action, 0.0
        segments = commands.split_inline(raw)
    else:
        segments = [raw]

    skip_cleanup = profile is not None and not profile.get("cleanup", True)
    style = profile.get("style") if profile else None

    llm_total = 0.0
    out = []
    for seg in segments:
        if commands.is_break(seg):
            out.append(seg)
            continue
        if skip_cleanup:
            out.append(seg)
            continue
        cleaned, llm_s, _used = cleaner.clean(seg, style=style)
        llm_total += llm_s
        out.append(cleaned)
    # join text segments; breaks glue directly
    final = ""
    for seg in out:
        if commands.is_break(seg):
            final = final.rstrip() + seg
        else:
            final += (" " if final and not final.endswith("\n") else "") + seg
    return final.strip(), None, llm_total


ACTIONS = {
    "undo": lambda: keyboard.send("ctrl+z"),
    "enter": lambda: keyboard.send("enter"),
    "tab": lambda: keyboard.send("tab"),
}


def main():
    _setup_headless_logging()
    if not _single_instance():
        print("[aurora-voice] another instance is already running - exiting")
        os._exit(0)  # hard exit: heavy imports (torch/ctranslate2) leave non-daemon
        # threads that would keep a plain `return` process alive as a zombie.
    cfg = config.load()
    print(f"[aurora-voice] loading ASR model {cfg['asr']['model']} "
          f"({cfg['asr']['compute_type']}) ...")
    transcriber = asr.Transcriber(cfg)
    if transcriber.initial_prompt:
        print(f"[aurora-voice] vocab bias: {transcriber.initial_prompt}")
    print(f"[aurora-voice] model loaded in {transcriber.load_s:.1f}s; warming up ...")
    transcriber.warmup(cfg["audio"]["sample_rate"])

    cleaner = cleanup.Cleaner(cfg)
    if cleaner.enabled:
        warm = cleaner.warmup()
        if warm is None:
            time.sleep(3)             # autostart can beat Ollama to the boot line
            warm = cleaner.warmup()   # one re-probe before giving up
        if warm is None:
            # Not a latch: clean() re-probes per call, so cleanup engages the
            # moment Ollama comes up - the first non-code dictation just pays a cold load.
            print("[aurora-voice] Ollama not ready - cleanup will engage automatically once it's up")
        else:
            print(f"[aurora-voice] cleanup LLM warm in {warm:.1f}s ({cfg['cleanup']['model']})")

    rec = audio.Recorder(cfg["audio"]["sample_rate"], cfg["audio"]["device"])
    rec.start_stream(timeout=15.0)  # generous: audio devices are slow at logon

    overlay_ui = None
    if cfg["ui"]["overlay"]:
        try:
            from app.overlay import Overlay
            overlay_ui = Overlay(cfg, lambda: rec.recent(2048))
            overlay_ui.start()
        except Exception as e:
            print(f"[aurora-voice] overlay disabled ({e})")

    tray = None
    if cfg["ui"]["tray"]:
        try:
            from app.tray import Tray
            tray = Tray(cfg, cleaner, on_quit=rec.close)
            tray.start()
        except Exception as e:
            print(f"[aurora-voice] tray disabled ({e})")

    def set_state(s):
        if tray:
            tray.set_state(s)
        if overlay_ui:
            if s == "rec":
                overlay_ui.show()
            elif s == "busy":
                overlay_ui.processing()
            else:
                overlay_ui.hide()

    jobs: queue.Queue = queue.Queue(maxsize=1)

    def worker():
        while True:
            clip, exe, target = jobs.get()
            set_state("busy")
            try:
                n_s = len(clip) / cfg["audio"]["sample_rate"]
                if n_s < cfg["ui"]["min_record_s"]:
                    print(f"  (skipped: {n_s:.2f}s too short)")
                    continue
                matched = context.match_profile(cfg, exe)
                prof_name, profile = matched if matched else (None, None)
                raw, asr_s = transcriber.transcribe(clip)
                if not raw:
                    print(f"  (no speech detected in {n_s:.1f}s clip)")
                    beep(cfg, 300)
                    continue
                text, action, llm_s = process_text(raw, cleaner, cfg, profile)
                # put focus back where the user was dictating, so text lands at
                # the original click even if they clicked away while we thought.
                context.restore_target(target)
                if action:
                    ACTIONS[action]()
                    print(f"  {n_s:.1f}s audio | asr {asr_s:.2f}s | command: {action}")
                    continue
                inj_s = inject.inject(text, cfg)
                ctx_note = f" | ctx {prof_name}({exe})" if prof_name else ""
                print(f"  {n_s:.1f}s audio | asr {asr_s:.2f}s({transcriber.last_device}) | llm {llm_s:.2f}s "
                      f"| inject {inj_s:.2f}s | total {asr_s + llm_s + inj_s:.2f}s{ctx_note}")
                print(f"  >> {text!r}" if "\n" in text else f"  >> {text}")
            except Exception as e:
                # ponytail: one ASR failure must not kill the worker thread and
                # wedge the maxsize=1 queue forever (was: unhandled -> thread dies
                # -> every later f9 dropped as "busy"). Log, beep, keep looping.
                print(f"  (transcription failed: {type(e).__name__}: {e})")
                beep(cfg, 300)
            finally:
                set_state("idle")

    threading.Thread(target=worker, daemon=True).start()

    key = cfg["hotkey"]["key"]
    mode = cfg["hotkey"]["mode"]
    state = {"down": False}

    def start_rec():
        state["down"] = True
        state["exe"] = context.get_foreground_exe()  # capture dictation target (profile)
        state["target"] = context.capture_target()   # capture window+control (inject)
        rec.begin()
        set_state("rec")
        beep(cfg, 880, 60)
        stop_hint = f"release {key}" if mode == "hold" else f"press {key} again"
        print(f"[rec] listening ... ({stop_hint} to transcribe)")

    def stop_rec():
        state["down"] = False
        clip = rec.end()
        set_state("busy")
        beep(cfg, 440, 60)
        try:
            jobs.put_nowait((clip, state.get("exe", ""), state.get("target")))
        except queue.Full:
            print("  (busy with previous dictation - dropped)")
            set_state("idle")

    if mode == "toggle":
        def on_press(_e):
            if state["down"]:
                stop_rec()
            else:
                start_rec()
        keyboard.on_press_key(key, on_press, suppress=True)
    else:  # hold
        def on_press(_e):
            if not state["down"]:
                start_rec()

        def on_release(_e):
            if state["down"]:
                stop_rec()
        keyboard.on_press_key(key, on_press, suppress=True)
        keyboard.on_release_key(key, on_release, suppress=True)

    print(f"[aurora-voice] ready - {mode} '{key}' to dictate. Ctrl+C here to quit.")
    try:
        keyboard.wait()
    except KeyboardInterrupt:
        pass
    finally:
        rec.close()


if __name__ == "__main__":
    main()
