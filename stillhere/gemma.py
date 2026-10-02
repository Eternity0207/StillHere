"""Tiny client for Gemma (open weights) served through the Google AI Studio API.

Swapping providers means changing this one file: anything that serves Gemma (Vertex, a GPU box running
vLLM, Ollama on a better laptop) can stand in.
"""
from __future__ import annotations

import json
import logging
import re
import time

import httpx

from . import config

log = logging.getLogger(__name__)
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GemmaError(RuntimeError):
    pass


def _call(model: str, system: str, user_parts: list[dict], as_json: bool, temperature: float) -> str:
    gen = {"temperature": temperature, "thinkingConfig": {"thinkingLevel": "minimal"}}
    if as_json:
        gen["responseMimeType"] = "application/json"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": user_parts}],
        "generationConfig": gen,
    }
    r = httpx.post(
        API.format(model=model), json=body, timeout=httpx.Timeout(30, connect=10),
        headers={"x-goog-api-key": config.GEMMA_API_KEY},
    )
    if r.status_code != 200:
        raise GemmaError(f"{model} {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as e:
        raise GemmaError(f"{model} returned no content: {str(data)[:300]}") from e
    # Gemma 4 can return its reasoning as parts flagged "thought"; only the answer matters here.
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def generate(system: str, prompt: str, *, image: tuple[str, str] | None = None,
             as_json: bool = False, temperature: float = 0.8) -> str:
    if not config.GEMMA_API_KEY:
        raise GemmaError("GEMMA_API_KEY is not set")
    parts: list[dict] = []
    if image:
        mime, b64 = image
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})
    parts.append({"text": prompt})
    # The hosted free tier has bursts of 500/503s; alternate between the two Gemma sizes with a short backoff.
    models = [config.GEMMA_MODEL, config.GEMMA_FALLBACK_MODEL, config.GEMMA_MODEL, config.GEMMA_FALLBACK_MODEL]
    last: Exception | None = None
    for attempt, model in enumerate(models):
        if attempt:
            time.sleep(min(2 ** attempt, 6))
        try:
            return _call(model, system, parts, as_json, temperature)
        except (GemmaError, httpx.HTTPError) as e:
            log.warning("gemma attempt %d (%s) failed: %s", attempt + 1, model, str(e)[:160])
            last = e
    raise GemmaError(str(last))


def generate_json(system: str, prompt: str, **kw) -> dict:
    raw = generate(system, prompt, as_json=True, **kw)
    return parse_json(raw)


def parse_json(raw: str) -> dict:
    """Be forgiving: Gemma sometimes wraps the object in a list or a code fence."""
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise GemmaError(f"not JSON: {raw[:200]}")
        data = json.loads(m.group(0))
    if isinstance(data, list):
        data = next((d for d in data if isinstance(d, dict)), {})
    if not isinstance(data, dict):
        raise GemmaError(f"unexpected JSON: {raw[:200]}")
    return data
