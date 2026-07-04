import os, sys, time, subprocess

# CTranslate2 >=4.5 on Windows needs CUDA 12 cuBLAS + cuDNN 9 DLLs. The nvidia-*-cu12
# pip wheels ship them under site-packages/nvidia/*/bin, but CT2 loads them with a
# plain LoadLibrary call, so add_dll_directory alone is not enough: prepend the dirs
# to PATH and preload the DLLs into the process with ctypes.
import ctypes

_site = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
if os.path.isdir(_site):
    for _sub in sorted(os.listdir(_site)):
        _bin = os.path.join(_site, _sub, "bin")
        if os.path.isdir(_bin):
            os.add_dll_directory(_bin)
            os.environ["PATH"] = _bin + os.pathsep + os.environ.get("PATH", "")
            for _dll in sorted(os.listdir(_bin)):
                if _dll.endswith(".dll"):
                    try:
                        ctypes.WinDLL(os.path.join(_bin, _dll))
                    except OSError:
                        pass  # some DLLs have deps loaded later; PATH covers them

from faster_whisper import WhisperModel

AUDIO = sys.argv[1] if len(sys.argv) > 1 else "test.wav"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "small"
COMPUTE_TYPES = sys.argv[3].split(",") if len(sys.argv) > 3 else ["int8", "float16"]


def vram():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"]
        ).decode().strip()
        used, free = [int(x) for x in out.split(",")]
        return f"VRAM used={used} MiB free={free} MiB"
    except Exception as e:
        return f"(vram query failed: {e})"


def try_run(compute_type):
    print(f"\n=== device=cuda | compute_type={compute_type} | model={MODEL} ===")
    print("before load:", vram())
    try:
        t0 = time.time()
        model = WhisperModel(MODEL, device="cuda", compute_type=compute_type)
        load = time.time() - t0
        print(f"after  load: {vram()}  (load {load:.2f}s)")
        text = ""
        for label in ("COLD", "WARM"):
            t1 = time.time()
            segments, info = model.transcribe(AUDIO, beam_size=5)
            text = " ".join(s.text for s in segments).strip()
            dur = time.time() - t1
            print(f"{label} TRANSCRIBE {dur:.2f}s | lang={info.language} p={info.language_probability:.2f} | audio={info.duration:.1f}s | RTF={dur/max(info.duration,0.01):.3f}")
        print("after transcribe:", vram())
        print("TEXT:", text)
        del model
        return True, text
    except Exception as e:
        print(f"!! FAILED ({compute_type}): {type(e).__name__}: {e}")
        return False, None


if __name__ == "__main__":
    print(f"audio={AUDIO}  model={MODEL}  compute_types={COMPUTE_TYPES}")
    print("baseline:", vram())
    results = {}
    for ct in COMPUTE_TYPES:
        ok, text = try_run(ct)
        results[ct] = ok
    print("\n=== SUMMARY ===")
    for ct, ok in results.items():
        print(f"  {ct:14s} -> {'OK' if ok else 'FAILED'}")
