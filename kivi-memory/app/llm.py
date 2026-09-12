"""Thin Gemini client used for text generation, tool-calling, and embeddings."""
from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types

from app.config import settings

_client: genai.Client | None = None


def gemini_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _schema_from_json(schema: dict) -> types.Schema:
    properties = {}
    for name, spec in (schema.get("properties") or {}).items():
        properties[name] = types.Schema(
            type=types.Type.STRING,
            description=spec.get("description"),
        )
    return types.Schema(
        type=types.Type.OBJECT,
        properties=properties or None,
        required=schema.get("required") or None,
    )


def gemini_tools_from_defs(tool_defs: list[dict]) -> list[types.Tool]:
    decls = [
        types.FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters=_schema_from_json(t.get("input_schema") or {}),
        )
        for t in tool_defs
    ]
    return [types.Tool(function_declarations=decls)]


def generate_text(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 1024,
) -> str:
    config = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_tokens,
        temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    resp = gemini_client().models.generate_content(
        model=model or settings.AGENT_MODEL,
        contents=prompt,
        config=config,
    )
    return (getattr(resp, "text", None) or "").strip()


def generate_with_tools(
    contents: list[types.Content],
    *,
    system: str,
    tools: list[types.Tool],
    model: str | None = None,
    max_tokens: int = 1536,
):
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=tools,
        max_output_tokens=max_tokens,
        temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    return gemini_client().models.generate_content(
        model=model or settings.AGENT_MODEL,
        contents=contents,
        config=config,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    resp = gemini_client().models.embed_content(
        model=settings.EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(output_dimensionality=settings.EMBEDDING_DIM),
    )
    embeddings = getattr(resp, "embeddings", None) or []
    return [list(e.values) for e in embeddings]


def function_calls_from_response(resp) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        return calls
    content = candidates[0].content
    for part in getattr(content, "parts", None) or []:
        fc = getattr(part, "function_call", None)
        if fc and getattr(fc, "name", None):
            args = dict(fc.args) if fc.args else {}
            calls.append((fc.name, args))
    return calls


def response_text(resp) -> str:
    text = getattr(resp, "text", None)
    if text:
        return text.strip()
    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        return ""
    parts = getattr(candidates[0].content, "parts", None) or []
    chunks = []
    for part in parts:
        value = getattr(part, "text", None)
        if value:
            chunks.append(value)
    return "".join(chunks).strip()
