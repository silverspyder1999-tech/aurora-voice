"""Ollama LLM cleanup pass (Phase 2).

Design rules (validated in Phase 0 / PHASE0_REPORT.md):
- Talk to 127.0.0.1, never "localhost" (~2 s IPv6 penalty per request on Windows).
- keep_alive holds the model in VRAM so warm latency stays ~0.3 s.
- The cleanup must never eat the user's words: any failure, timeout, or
  suspicious output falls back to the raw transcript.
"""
import json
import time
import urllib.error
import urllib.request

SYSTEM = (
    "You are a dictation cleanup engine. Rewrite the user's dictated text with "
    "correct punctuation, capitalization, and spacing. Remove filler words (um, uh, "
    "like, you know) and false starts or repeated words. Fix obvious grammar slips. "
    "Preserve the speaker's wording, meaning, and tone - do not paraphrase, "
    "summarize, expand, or answer questions contained in the text. Output only the "
    "cleaned text, with no preamble, quotes, or commentary."
)

# Compact few-shot pair keeps a 3B model on-task (cheap: prompt tokens process fast).
FEWSHOT = [
    {"role": "user", "content": "um so basically i think we should uh push the "
     "deadline to friday because like the design isnt done yet"},
    {"role": "assistant", "content": "I think we should push the deadline to Friday "
     "because the design isn't done yet."},
    {"role": "user", "content": "hey can you um send me the the report before lunch thanks"},
    {"role": "assistant", "content": "Hey, can you send me the report before lunch? Thanks."},
]


class Cleaner:
    def __init__(self, cfg: dict):
        c = cfg["cleanup"]
        self.enabled = c["enabled"]
        self.url = c["url"].rstrip("/")
        self.model = c["model"]
        self.keep_alive = c["keep_alive"]
        self.timeout_s = c["timeout_s"]
        self.system = SYSTEM
        words = cfg.get("vocab", {}).get("words", [])
        if words:
            self.system += (
                " If a word is a close phonetic match for one of these exact "
                "spellings, use the exact spelling: " + ", ".join(words) + "."
            )

    def _chat(self, user_text: str, timeout: float, style: str | None = None) -> str:
        system = self.system + (f" Style for this text: {style}" if style else "")
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *FEWSHOT,
                         {"role": "user", "content": user_text}],
            "stream": False,
            "think": False,  # qwen3.5 & other reasoning models: skip <think> so the
                             # answer lands in message.content within the time budget
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0.1},
        }).encode()
        req = urllib.request.Request(
            f"{self.url}/api/chat", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["message"]["content"].strip()

    def warmup(self) -> float | None:
        """Load the model into VRAM at app start. Returns seconds, or None on failure."""
        if not self.enabled:
            return None
        try:
            t0 = time.time()
            self._chat("ok", timeout=120)  # cold load can take ~5-10 s
            return time.time() - t0
        except (urllib.error.URLError, OSError, KeyError, TimeoutError):
            return None

    def clean(self, text: str, style: str | None = None) -> tuple[str, float, bool]:
        """Returns (text, seconds, used_llm). Falls back to raw on any problem."""
        if not self.enabled or not text:
            return text, 0.0, False
        t0 = time.time()
        try:
            out = self._chat(text, timeout=self.timeout_s, style=style)
        except (urllib.error.URLError, OSError, KeyError, TimeoutError):
            return text, time.time() - t0, False
        took = time.time() - t0
        out = out.strip().strip('"').strip()
        # Suspicious-output guards: model went off-task -> keep the user's words.
        if not out:
            return text, took, False
        if len(out) > max(len(text) * 2, len(text) + 80):
            return text, took, False  # answered/expanded instead of cleaning
        return out, took, True
