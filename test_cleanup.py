import json
import sys
import time
import urllib.request

MODEL = sys.argv[1] if len(sys.argv) > 1 else "huihui_ai/llama3.2-abliterate:latest"
OLLAMA = "http://127.0.0.1:11434"  # not "localhost": Windows tries ::1 first, ~2s penalty

SYSTEM = (
    "You clean up dictated text. Fix punctuation and capitalization, remove filler words "
    "(um, uh, like, you know), and fix obvious grammar slips. Preserve the meaning and "
    "wording. Output ONLY the corrected text - no preamble, no explanation, no quotes."
)

MESSY = (
    "um so basically i think we should uh move the meeting to thursday because like "
    "the client isnt gonna be ready by tuesday and uh you know we still need to um "
    "finish the the slide deck and get feedback from sarah before we send it out"
)


def chat(model, system, user, keep_alive="5m"):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "keep_alive": keep_alive,
        "options": {"temperature": 0.1},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        resp = json.loads(r.read())
    wall = time.time() - t0
    return resp, wall


if __name__ == "__main__":
    print(f"model: {MODEL}")
    print(f"input ({len(MESSY)} chars): {MESSY}\n")

    # First call includes model load (cold start)
    resp, wall = chat(MODEL, SYSTEM, MESSY)
    text = resp["message"]["content"].strip()
    load_ns = resp.get("load_duration", 0)
    eval_ns = resp.get("eval_duration", 0)
    prompt_ns = resp.get("prompt_eval_duration", 0)
    print(f"COLD: wall={wall:.2f}s load={load_ns/1e9:.2f}s prompt_eval={prompt_ns/1e9:.2f}s eval={eval_ns/1e9:.2f}s")
    print(f"OUTPUT: {text}\n")

    # Second call = warm latency (the number that matters for the dictation loop)
    resp2, wall2 = chat(MODEL, SYSTEM, MESSY)
    text2 = resp2["message"]["content"].strip()
    eval2 = resp2.get("eval_duration", 0) / 1e9
    prompt2 = resp2.get("prompt_eval_duration", 0) / 1e9
    tokens2 = resp2.get("eval_count", 0)
    tps = tokens2 / eval2 if eval2 > 0 else 0
    print(f"WARM: wall={wall2:.2f}s prompt_eval={prompt2:.2f}s eval={eval2:.2f}s ({tokens2} tok, {tps:.0f} tok/s)")
    print(f"OUTPUT: {text2}")
