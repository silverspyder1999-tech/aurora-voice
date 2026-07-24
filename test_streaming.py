"""Unit test for instant-mode LocalAgreement-2 commit logic (app/streaming.py).

Pure: feeds scripted transcriptions, captures what would be typed. No mic/GPU/keyboard.

Run:  venv\\Scripts\\python.exe test_streaming.py
"""
from app.streaming import InstantSession


def run(ticks, final):
    out = []
    s = InstantSession(out.append)
    for t in ticks:
        s.tick(t)
    s.finalize(final)
    return out, s


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    assert ok, name


# 1. Growing buffer: a word commits once two ticks agree; finalize types the tail.
out, _ = run(["the quick brown", "the quick brown fox"], "the quick brown fox jumps")
check("agreement commits stable prefix", out == ["the quick brown", " fox jumps"], repr(out))
check("joined text is correct", "".join(out) == "the quick brown fox jumps")

# 2. Volatile tail is corrected before it's ever typed (word -> world).
out, _ = run(["hello word", "hello world"], "hello world")
check("volatile tail held then corrected", out == ["hello", " world"], repr(out))

# 3. A9: empty / silent recording types nothing (no crash, no stray space).
out, _ = run(["", "", ""], "")
check("silence emits nothing", out == [], repr(out))

# 4. Utterance shorter than the tick interval: nothing agrees, finalize types all.
out, _ = run(["hello there"], "hello there")
check("single-tick utterance finalizes whole", out == ["hello there"], repr(out))

# 5. Over-eager commit can't underflow: finalize shorter than committed types nothing extra.
out, s = run(["a b c d", "a b c d"], "a b")
check("finalize shorter than committed is safe", out == ["a b c d"] and s._committed == 4, repr(out))

# 6. A committed word is never typed twice (monotonic commit).
out, _ = run(["one two", "one two", "one two three", "one two three"], "one two three four")
check("no word typed twice", "".join(out) == "one two three four", repr(out))

print("\nSTREAMING TEST PASSED")
