"""CUDA DLL bootstrap for CTranslate2 on Windows.

CTranslate2 >=4.5 needs CUDA 12 cuBLAS + cuDNN 9 DLLs. The nvidia-*-cu12 pip wheels
ship them under site-packages/nvidia/*/bin, but CT2 loads them with a plain
LoadLibrary call, so os.add_dll_directory alone is NOT enough: we also prepend the
dirs to PATH and preload every DLL into the process with ctypes.

Validated on RTX 5080 (sm_120) / driver 610.62 / CT2 4.8.1 — see PHASE0_REPORT.md.
Must be imported BEFORE faster_whisper/ctranslate2.
"""
import ctypes
import os
import sys


def preload_cuda_dlls() -> list[str]:
    """Register and preload nvidia wheel DLLs. Returns the dirs that were added."""
    added = []
    site = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    if not os.path.isdir(site):
        return added
    for sub in sorted(os.listdir(site)):
        bin_dir = os.path.join(site, sub, "bin")
        if not os.path.isdir(bin_dir):
            continue
        os.add_dll_directory(bin_dir)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        for dll in sorted(os.listdir(bin_dir)):
            if dll.endswith(".dll"):
                try:
                    ctypes.WinDLL(os.path.join(bin_dir, dll))
                except OSError:
                    pass  # some DLLs resolve deps later; PATH covers them
        added.append(bin_dir)
    return added
