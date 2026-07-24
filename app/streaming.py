"""Instant mode: stream words to the cursor as you speak.

The growing audio buffer is re-transcribed every interval; a word is *committed*
(typed) only once two consecutive transcriptions agree on it - LocalAgreement-2
(Machacek et al., "Turning Whisper into Real-Time Transcription System"). The
volatile tail is held back until it stabilises, so the user rarely sees a word
get typed and then contradicted.

Trade-offs vs batch mode, by design:
- No LLM cleanup and no voice commands: you can't clean or interpret half a
  sentence, and immediacy is the whole point of instant mode.
- Already-typed words are never revised. If the final pass disagrees with a
  committed prefix, the committed text stands as typed.
  # ponytail: no revision of typed text; upgrade path is backspace-and-retype
  #   diffing against the committed prefix, only worth it if users complain.

This module is pure: it takes transcribed TEXT and an emit() callback, so the
commit algorithm is testable without a mic, GPU, or keyboard (see test_streaming.py).
"""


def _common_prefix_len(a: list, b: list) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


class InstantSession:
    def __init__(self, emit):
        """emit(text): types `text` at the cursor (e.g. keyboard.write)."""
        self._emit = emit
        self._prev: list[str] = []   # previous hypothesis (word list)
        self._committed = 0          # number of words already typed
        self._any = False            # anything emitted yet? (leading-space control)

    def tick(self, text: str) -> None:
        """Feed the transcription of the buffer so far; type any newly-stable words."""
        curr = text.split()
        agreed = _common_prefix_len(self._prev, curr)
        if agreed > self._committed:
            self._out(curr[self._committed:agreed])
            self._committed = agreed
        self._prev = curr

    def finalize(self, text: str) -> None:
        """Feed the final full-buffer transcription; type whatever tail is left."""
        curr = text.split()
        if len(curr) > self._committed:
            self._out(curr[self._committed:])
        self._committed = max(self._committed, len(curr))

    def _out(self, words: list) -> None:
        if not words:
            return
        self._emit((" " if self._any else "") + " ".join(words))
        self._any = True
