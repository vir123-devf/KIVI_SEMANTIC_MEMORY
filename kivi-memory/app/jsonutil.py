"""Defensive JSON parsing for LLM output that may include markdown fences."""
import json
from typing import Any


def parse_json_payload(text: str) -> Any:
    if text is None:
        raise json.JSONDecodeError("empty", "", 0)
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(raw):
        if ch in "{[":
            try:
                obj, _ = decoder.raw_decode(raw[i:])
                return obj
            except json.JSONDecodeError:
                continue
    return json.loads(raw)
