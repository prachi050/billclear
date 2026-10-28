"""Small client for the Meta Model API (OpenAI-compatible Chat Completions).

Details from the official docs (dev.meta.ai):
  base URL  https://api.meta.ai/v1
  auth      Authorization: Bearer $MODEL_API_KEY
  endpoint  POST /v1/chat/completions
  images    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}} in a user message
  models    default "muse-spark-1.3"; list with GET /v1/models

Settings come from environment variables on your own computer. Never put the key in code, in a file you upload,
or in the browser:
  MODEL_API_KEY      required
  META_API_BASE      optional, default https://api.meta.ai/v1
  META_MODEL         optional, default muse-spark-1.3
  META_REASONING     optional: minimal, low, medium or high. Lower means less thinking, fewer empty replies.
"""
import base64, os
import httpx

DEFAULT_BASE = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"


class MetaError(Exception):
    """A readable problem. Never includes the API key."""


def configured() -> bool:
    return bool(os.environ.get("MODEL_API_KEY"))


def _settings():
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise MetaError("MODEL_API_KEY is not set.")
    return os.environ.get("META_API_BASE", DEFAULT_BASE).rstrip("/"), key, os.environ.get("META_MODEL", DEFAULT_MODEL)


def _post(path: str, payload: dict, timeout: int = 60) -> dict:
    base, key, _ = _settings()
    try:
        r = httpx.post(f"{base}{path}", json=payload, timeout=timeout, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as e:
        raise MetaError(f"Could not reach the Meta Model API ({type(e).__name__}).")
    if r.status_code == 401:
        raise MetaError("The API key was rejected (401). Check MODEL_API_KEY.")
    if r.status_code == 429:
        raise MetaError("Rate limit or credit limit reached (429).")
    if r.status_code >= 400:
        raise MetaError(f"The API returned {r.status_code}: {r.text[:200]}")
    return r.json()


def chat(content, max_tokens: int = 1500) -> str:
    """Send one user message. `content` is a string, or a list of text/image parts. Returns the reply text.
    Retries once if the reply is empty (some models spend their token budget thinking and return nothing)."""
    _, _, model = _settings()
    last = "The API returned an empty reply."
    for attempt, limit in enumerate((max_tokens, max_tokens * 3)):
        payload = {"model": model, "max_tokens": limit, "messages": [{"role": "user", "content": content}]}
        effort = os.environ.get("META_REASONING")  # optional: minimal, low, medium, high
        if effort:
            payload["reasoning_effort"] = effort
        try:
            data = _post("/chat/completions", payload)
        except MetaError as e:
            if effort and "returned 400" in str(e):  # this model may not accept the setting: retry without it
                payload.pop("reasoning_effort")
                data = _post("/chat/completions", payload)
            else:
                raise
        try:
            choice = data["choices"][0]
            msg = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise MetaError("The API reply was not in the expected format.")
        if isinstance(msg, list):  # some APIs return a list of parts
            msg = "".join(p.get("text", "") for p in msg if isinstance(p, dict))
        if msg and msg.strip():
            return msg.strip()
        last = f"The API returned an empty reply (finish reason: {choice.get('finish_reason')})."
    raise MetaError(last)


def image_part(image: bytes) -> dict:
    mime = "image/png" if image[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode()}"}}


def list_models() -> list[str]:
    base, key, _ = _settings()
    try:
        r = httpx.get(f"{base}/models", timeout=30, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as e:
        raise MetaError(f"Could not reach the Meta Model API ({type(e).__name__}).")
    if r.status_code >= 400:
        raise MetaError(f"The API returned {r.status_code}: {r.text[:200]}")
    return [m.get("id", "?") for m in r.json().get("data", [])]
