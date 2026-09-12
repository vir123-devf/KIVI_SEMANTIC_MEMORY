"""
Tool definitions for the Hey Kivi agent loop, plus the dispatcher that
executes a tool call against the DB.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.retrieval import search_episodes, get_facts, get_preferences


TOOLS = [
    {
        "name": "search_episodes",
        "description": (
            "Find past dictations by semantic query, time range, and/or source app. "
            "Use this for requests like 'find the dictation about X' or "
            "'what did I say yesterday in Slack around 5pm'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Semantic search text, optional"},
                "time_start": {"type": "string", "description": "ISO 8601 datetime, optional"},
                "time_end": {"type": "string", "description": "ISO 8601 datetime, optional"},
                "source_app": {"type": "string", "description": "e.g. 'slack', 'gmail', 'docs'"},
            },
        },
    },
    {
        "name": "get_facts",
        "description": "Retrieve known durable facts about the user, optionally filtered by a subject-related query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject_query": {"type": "string", "description": "e.g. 'manager', 'project name'"},
            },
        },
    },
    {
        "name": "get_preferences",
        "description": "Retrieve the user's known stylistic/behavioral preferences, optionally filtered by category (e.g. 'tone', 'formatting', 'signoff').",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
            },
        },
    },
    {
        "name": "polish_text",
        "description": (
            "Rewrite/polish a piece of text, applying the user's known style preferences. "
            "Call get_preferences first if you haven't already, and pass relevant preferences in as context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "instructions": {"type": "string", "description": "e.g. 'for a meeting I am walking into'"},
                "preferences_context": {"type": "string", "description": "relevant preference descriptions, comma separated"},
            },
            "required": ["text"],
        },
    },
]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _polish_text(text: str, instructions: str = "", preferences_context: str = "") -> str:
    prompt = f"""Rewrite the following text to be polished and ready to send.
{f"Context/purpose: {instructions}" if instructions else ""}
{f"Apply these known user style preferences: {preferences_context}" if preferences_context else ""}

Text:
{text}

Return only the rewritten text, nothing else."""
    from app.llm import generate_text
    return generate_text(prompt, model=settings.AGENT_MODEL, max_tokens=1024)


def dispatch_tool(db: Session, user_id: UUID, name: str, tool_input: dict) -> dict:
    """Executes one tool call, returns a JSON-serializable result that
    always includes source IDs so the agent (and the eval harness) can
    trace every claim back to its provenance."""
    tool_input = tool_input or {}

    if name == "search_episodes":
        time_start = _parse_dt(tool_input.get("time_start"))
        time_end = _parse_dt(tool_input.get("time_end"))
        episodes = search_episodes(
            db, user_id,
            query=tool_input.get("query"),
            time_start=time_start, time_end=time_end,
            source_app=tool_input.get("source_app"),
        )
        return {
            "results": [
                {
                    "episode_id": str(e.id),
                    "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                    "source_app": e.source_app,
                    "summary": e.summary,
                    "text": e.formatted_text,
                }
                for e in episodes
            ]
        }

    if name == "get_facts":
        facts = get_facts(db, user_id, subject_query=tool_input.get("subject_query"))
        return {
            "results": [
                {"fact_id": str(f.id), "subject": f.subject, "value": f.value,
                 "confidence": f.confidence,
                 "source_episode_ids": [str(i) for i in (f.source_episode_ids or [])]}
                for f in facts
            ]
        }

    if name == "get_preferences":
        prefs = get_preferences(db, user_id, category=tool_input.get("category"))
        return {
            "results": [
                {"preference_id": str(p.id), "category": p.category, "description": p.description,
                 "strength": p.strength, "evidence_count": p.evidence_count}
                for p in prefs
            ]
        }

    if name == "polish_text":
        if not settings.GEMINI_API_KEY:
            return {"polished_text": tool_input.get("text", "")}
        polished = _polish_text(
            tool_input["text"],
            tool_input.get("instructions", "") or "",
            tool_input.get("preferences_context", "") or "",
        )
        return {"polished_text": polished}

    return {"error": f"unknown tool: {name}"}
