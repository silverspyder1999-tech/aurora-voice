"""Config loading: config.toml over built-in defaults."""
import copy
import tomllib
from pathlib import Path

DEFAULTS = {
    "hotkey": {
        "key": "f9",        # push-to-talk key
        "mode": "hold",     # hold | toggle (toggle lands in Phase 3)
    },
    "audio": {
        "sample_rate": 16000,
        "device": "",       # "" = system default input
    },
    "asr": {
        "model": "large-v3",
        "compute_type": "float16",  # int8 also validated on this GPU (lower VRAM)
        "language": "en",
        "beam_size": 5,
        "vad_filter": True,          # Silero VAD via faster-whisper
        "initial_prompt": "",        # custom vocabulary biasing (Phase 3)
    },
    "cleanup": {                     # Phase 2
        "enabled": False,
        "model": "llama3.2:latest",
        "url": "http://127.0.0.1:11434",  # NEVER "localhost" (2s IPv6 penalty)
        "keep_alive": "30m",
        "timeout_s": 8.0,            # past this, inject the raw transcript instead
    },
    "inject": {
        "method": "paste",           # paste | type
        "restore_clipboard": True,
        "restore_delay_s": 0.4,
    },
    "vocab": {                       # Phase 3: personal dictionary
        "words": [],                 # e.g. ["Ollama", "CTranslate2", "Wispr"]
    },
    "commands": {                    # Phase 3: voice commands
        "enabled": True,
    },
    "profiles": {                    # Phase 4: per-app context profiles
        "code": {
            "match": ["Code.exe", "WindowsTerminal.exe", "devenv.exe",
                      "pycharm64.exe", "idea64.exe", "OpenConsole.exe"],
            "cleanup": False,        # raw transcript: don't mangle identifiers
        },
        "email": {
            "match": ["olk.exe", "OUTLOOK.EXE", "thunderbird.exe", "HxOutlook.exe"],
            "style": "Professional business tone with complete sentences.",
        },
        "chat": {
            "match": ["Discord.exe", "Slack.exe", "ms-teams.exe", "Telegram.exe",
                      "WhatsApp.exe"],
            "style": "Casual chat tone. Keep contractions. No trailing period "
                     "on short messages.",
        },
    },
    "ui": {
        "sounds": True,
        "min_record_s": 0.3,         # ignore accidental taps
        "tray": True,                # system tray icon
        "overlay": True,             # voice-wave overlay while dictating
        "overlay_opacity": 0.85,     # 0..1 window translucency
        "overlay_margin_bottom": 24, # px above the taskbar
    },
}


def load(path: str | Path = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    path = Path(path) if path else Path(__file__).resolve().parent.parent / "config.toml"
    if path.is_file():
        with open(path, "rb") as f:
            user = tomllib.load(f)
        for section, values in user.items():
            cfg.setdefault(section, {}).update(values)
    return cfg
