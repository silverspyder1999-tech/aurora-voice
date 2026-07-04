"""Voice commands (Phase 3).

Two kinds:
- Whole-utterance commands: the entire dictation IS the command
  ("delete that" -> Ctrl+Z; our paste is a single edit op in most apps).
- Inline commands: markers inside the dictation ("new paragraph" -> \\n\\n).
  Text is split on them BEFORE LLM cleanup so the LLM can't flatten the breaks;
  each text segment is cleaned separately and rejoined.
"""
import re

# normalized whole-utterance text -> action name (executed in main.py)
UTTERANCE_COMMANDS = {
    "delete that": "undo",
    "scratch that": "undo",
    "undo that": "undo",
    "undo": "undo",
    "press enter": "enter",
    "hit enter": "enter",
    "press tab": "tab",
}

# inline spoken marker -> literal text. Longest-first so "new paragraph" wins.
INLINE_COMMANDS = [
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
    ("newline", "\n"),
]

_INLINE_RE = re.compile(
    r"[ ,.]*\b(" + "|".join(re.escape(k) for k, _ in INLINE_COMMANDS) + r")\b[ ,.]*",
    re.IGNORECASE,
)
_INLINE_MAP = {k.lower(): v for k, v in INLINE_COMMANDS}


def normalize(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


def whole_utterance(text: str) -> str | None:
    """Return an action name if the entire utterance is a command, else None."""
    return UTTERANCE_COMMANDS.get(normalize(text))


def split_inline(text: str) -> list[str]:
    """Split text into segments; inline command markers become their literal text.

    "so first point new paragraph second point" ->
    ["so first point", "\\n\\n", "second point"]
    """
    parts = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            parts.append(before)
        parts.append(_INLINE_MAP[m.group(1).lower()])
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        parts.append(tail)
    return parts if parts else [text]


def is_break(segment: str) -> bool:
    return segment in ("\n", "\n\n")
