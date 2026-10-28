"""Run this once after you set MODEL_API_KEY. It tests the connection step by step and tells you what failed.
    export MODEL_API_KEY=...        (in your own terminal, never in a file)
    python scripts/check_meta.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import metaclient, reader


def step(name, fn):
    try:
        out = fn(); print(f"OK    {name}: {out}"); return out
    except Exception as e:
        print(f"FAIL  {name}: {e}"); return None


print("Using model:", os.environ.get("META_MODEL", metaclient.DEFAULT_MODEL))
step("key is set", lambda: "yes" if metaclient.configured() else (_ for _ in ()).throw(RuntimeError("MODEL_API_KEY is not set")))
step("list models", lambda: ", ".join(metaclient.list_models()[:8]))
step("text reply", lambda: metaclient.chat("Reply with the single word: ready", max_tokens=20))
img = open(os.path.join(os.path.dirname(__file__), "..", "static", "samples", "duplicate.png"), "rb").read()
text = step("read sample image", lambda: metaclient.chat([{"type": "text", "text": "Copy the text of this image exactly."}, metaclient.image_part(img)], max_tokens=900))
if text:
    f = reader.parse_text(text)
    print("parsed:", {k: f[k] for k in ("provider", "billed", "patient_owes")}, "| problems:", reader.verify_extraction(f) or "none")
