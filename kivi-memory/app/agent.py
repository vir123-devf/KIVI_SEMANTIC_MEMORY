"""
The Hey Kivi agent loop using Gemini function calling. The final answer must
be structured JSON that names exactly which episode/fact/preference IDs it used.
"""
import json
import time
from uuid import UUID

from google.genai import types
from sqlalchemy.orm import Session

from app.config import settings
from app.tools import TOOLS, dispatch_tool
from app.schemas import HeyKiviResponse
from app.jsonutil import parse_json_payload
from app.llm import (
    function_calls_from_response,
    gemini_tools_from_defs,
    generate_with_tools,
    response_text,
)

SYSTEM_PROMPT = """You are Hey Kivi, a voice assistant with access to the user's dictation
history, known facts, and known preferences via tools.

Rules:
- Only use information returned by tools. Never invent or assume facts, dates, or content
  that tools did not return.
- If the tools do not contain enough information to answer, say so plainly instead of guessing.
- Call get_preferences before using polish_text if the request involves rewriting/polishing text.
- When you have enough information, respond with ONLY a JSON object (no prose outside it,
  no markdown fences) in exactly this shape:

{
  "answer": "<your natural-language answer to the user>",
  "episode_ids": ["<uuid>", ...],
  "fact_ids": ["<uuid>", ...],
  "preference_ids": ["<uuid>", ...]
}

Leave an array empty if you used nothing of that type. If you could not answer, still
return this JSON shape with "answer" explaining why, and empty id arrays unless you
partially grounded the explanation in something you found."""


def _as_uuids(values) -> list[UUID]:
    out = []
    for item in values or []:
        try:
            out.append(UUID(str(item)))
        except (ValueError, TypeError, AttributeError):
            continue
    return out


def run_hey_kivi(db: Session, user_id: UUID, message: str) -> HeyKiviResponse:
    start = time.perf_counter()
    if not settings.GEMINI_API_KEY:
        return HeyKiviResponse(
            answer="Hey Kivi needs GEMINI_API_KEY in .env to answer questions.",
            tool_trace=[],
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    contents = [types.Content(role="user", parts=[types.Part.from_text(text=message)])]
    tools = gemini_tools_from_defs(TOOLS)
    tool_trace = []

    for _ in range(6):
        resp = generate_with_tools(
            contents,
            system=SYSTEM_PROMPT,
            tools=tools,
            model=settings.AGENT_MODEL,
        )
        calls = function_calls_from_response(resp)
        if not calls:
            final_text = response_text(resp)
            parsed = _parse_final_answer(final_text)
            latency_ms = (time.perf_counter() - start) * 1000
            return HeyKiviResponse(
                answer=parsed.get("answer") or final_text,
                cited_episode_ids=_as_uuids(parsed.get("episode_ids", [])),
                cited_fact_ids=_as_uuids(parsed.get("fact_ids", [])),
                cited_preference_ids=_as_uuids(parsed.get("preference_ids", [])),
                tool_trace=tool_trace,
                latency_ms=latency_ms,
            )

        model_content = resp.candidates[0].content
        contents.append(model_content)
        result_parts = []
        for name, args in calls:
            result = dispatch_tool(db, user_id, name, args)
            tool_trace.append({"tool": name, "input": args, "result": result})
            result_parts.append(
                types.Part.from_function_response(name=name, response={"result": result})
            )
        contents.append(types.Content(role="user", parts=result_parts))

    latency_ms = (time.perf_counter() - start) * 1000
    return HeyKiviResponse(
        answer="I wasn't able to complete this request within my tool-call limit.",
        tool_trace=tool_trace, latency_ms=latency_ms,
    )


def _parse_final_answer(text: str) -> dict:
    try:
        parsed = parse_json_payload(text)
        if isinstance(parsed, dict) and "answer" in parsed:
            return parsed
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return {"answer": text, "episode_ids": [], "fact_ids": [], "preference_ids": []}
