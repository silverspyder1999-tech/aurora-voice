"""System tray icon (Phase 3). Green = idle, red = recording, gray = busy.

pystray runs detached on its own thread; main.py calls set_state().
"""
import os

import pystray
from PIL import Image, ImageDraw

COLORS = {"idle": (46, 160, 67), "rec": (218, 54, 51), "busy": (140, 140, 140)}


def _icon_image(color) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([8, 8, 56, 56], fill=color)
    d.ellipse([22, 18, 42, 40], fill=(255, 255, 255, 230))   # mic capsule
    d.rectangle([30, 40, 34, 48], fill=(255, 255, 255, 230))  # mic stem
    return img


class Tray:
    def __init__(self, cfg: dict, cleaner, on_quit=None):
        self._cleaner = cleaner
        self._on_quit = on_quit
        self._icon = pystray.Icon(
            "aurora-voice",
            _icon_image(COLORS["idle"]),
            f"Aurora Voice - hold {cfg['hotkey']['key']} to dictate",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "AI cleanup",
                    self._toggle_cleanup,
                    checked=lambda item: self._cleaner.enabled,
                ),
                pystray.MenuItem("Quit", self._quit),
            ),
        )

    def _toggle_cleanup(self, icon, item):
        self._cleaner.enabled = not self._cleaner.enabled

    def _quit(self, icon, item):
        icon.stop()
        if self._on_quit:
            self._on_quit()
        os._exit(0)

    def start(self):
        self._icon.run_detached()

    def set_state(self, state: str):
        self._icon.icon = _icon_image(COLORS.get(state, COLORS["idle"]))
