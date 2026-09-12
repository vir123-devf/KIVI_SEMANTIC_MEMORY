"""
The five Hey Kivi tools. Each tool is intentionally narrow and returns
structured, inspectable output (never just a string) so the orchestration
layer's reasoning and the eval harness can both point at exactly which
rows backed an answer.
"""
from datetime import datetime, timezone

from db import get_conn, embed, cosine, blob_to_vec, now_iso, new_id
import memory as mem

TOOL_SCHEMAS = [
    {
        "name": "search_dictations",
        "description": "Semantically search the user's past dictations. Optionally restrict to a time window.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "hours_ago_min": {"type": "number", "description": "Lower bound of how many hours ago, e.g. 20"},
                "hours_ago_max": {"type": "number", "description": "Upper bound of how many hours ago, e.g. 28"},
                "app_context": {"type": "string", "description": "e.g. Slack, Gmail"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "recall_durable",
        "description": "Retrieve facts and/or preferences relevant to a topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {"type": "string", "enum": ["fact", "preference", "any"]},
            },
            "required": ["query"],
        },
    },
    {
        "name": "polish_text",
        "description": "Rewrite a passage applying the user's known preferences (tone, format, sign-off, etc).",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "purpose": {"type": "string", "description": "e.g. 'for a meeting', 'for a Slack update'"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "remember",
        "description": "Explicitly store a new fact or preference the user just stated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "kind": {"type": "string", "enum": ["fact", "preference"]},
            },
            "required": ["content", "kind"],
        },
    },
    {
        "name": "forget",
        "description": "Delete a memory the user no longer wants stored. Requires the memory_id from a prior recall_durable/search_dictations call.",
        "input_schema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    },
]


def search_dictations(query: str, hours_ago_min: float = None, hours_ago_max: float = None,
                       app_context: str = None) -> dict:
    vec = embed(query)
    conn = get_conn()
    rows = conn.execute("SELECT * FROM dictations").fetchall()
    conn.close()

    now = datetime.now(timezone.utc)
    hits = []
    for r in rows:
        ts = datetime.fromisoformat(r["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = (now - ts).total_seconds() / 3600.0
        if hours_ago_min is not None and age_h < hours_ago_min:
            continue
        if hours_ago_max is not None and age_h > hours_ago_max:
            continue
        if app_context and (r["app_context"] or "").lower() != app_context.lower():
            continue
        text = r["llm_formatted"] or r["raw_asr"]
        # naive: embed on the fly. For 500 rows this is fine; for scale,
        # precompute + store an embedding column on dictations too.
        sim = cosine(vec, embed(text))
        hits.append({"dictation_id": r["id"], "ts": r["ts"], "app_context": r["app_context"],
                      "text": text, "similarity": round(sim, 3)})
    hits.sort(key=lambda x: -x["similarity"])
    return {"results": hits[:5]}


def recall_durable(query: str, kind: str = "any") -> dict:
    kinds = None if kind == "any" else [kind]
    results = mem.retrieve(query, kinds=kinds, top_k=5)
    return {"results": results}


def polish_text(text: str, purpose: str = "") -> dict:
    prefs = mem.retrieve(f"writing style preferences relevant to: {purpose or text}",
                          kinds=["preference"], top_k=4)
    # Actual rewriting is done by the orchestration model using this context;
    # this tool's job is just to surface the grounding preferences.
    return {"source_text": text, "purpose": purpose, "applicable_preferences": prefs}


def remember(content: str, kind: str) -> dict:
    vec = embed(content)
    mem_id = mem._insert_memory(kind, content, 0.95, vec, None, content, "explicit_user")
    return {"memory_id": mem_id, "stored": content, "kind": kind}


def forget(memory_id: str) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT content FROM memories WHERE id=?", (memory_id,)).fetchone()
    if not row:
        conn.close()
        return {"deleted": False, "reason": "memory_id not found"}
    conn.execute("UPDATE memories SET status='rejected', updated_at=? WHERE id=?", (now_iso(), memory_id))
    conn.commit()
    conn.close()
    return {"deleted": True, "content": row["content"]}


DISPATCH = {
    "search_dictations": search_dictations,
    "recall_durable": recall_durable,
    "polish_text": polish_text,
    "remember": remember,
    "forget": forget,
}
