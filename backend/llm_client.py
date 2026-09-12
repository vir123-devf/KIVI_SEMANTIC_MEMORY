"""
Wrapper around the Anthropic API. Two model tiers are used deliberately:

- EXTRACTION_MODEL (cheap/fast, e.g. Haiku): runs on every dictation in the
  background. High volume, low per-call complexity (structured extraction),
  so cost/latency matter more than raw capability here.
- ORCHESTRATION_MODEL (stronger, e.g. Sonnet): runs on every Hey Kivi turn.
  Needs to select tools correctly, reason over retrieved memories, and
  refuse to invent answers when memory doesn't cover the question, so it's
  worth the extra cost per call (these are low-volume, user-facing, and
  wrong-tool-use or hallucination here is the expensive failure mode).
"""
import os
import json
import time
from anthropic import Anthropic

_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

EXTRACTION_MODEL = os.environ.get("KIVI_EXTRACTION_MODEL", "claude-haiku-4-5-20251001")
ORCHESTRATION_MODEL = os.environ.get("KIVI_ORCHESTRATION_MODEL", "claude-sonnet-4-6")


def call(model: str, system: str, messages: list, tools: list | None = None,
         max_tokens: int = 1024):
    """Single entry point so latency/token usage can be captured uniformly."""
    start = time.time()
    kwargs = dict(model=model, system=system, messages=messages, max_tokens=max_tokens)
    if tools:
        kwargs["tools"] = tools
    resp = _client.messages.create(**kwargs)
    latency_ms = int((time.time() - start) * 1000)
    return resp, latency_ms


def extract_json(text: str) -> dict | list:
    """LLM extraction prompts are instructed to return only JSON; this
    strips accidental code fences before parsing."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())
