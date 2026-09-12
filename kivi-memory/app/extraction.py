"""
Extraction pipeline.

For every episode (dictation event):
  1. Ask the LLM to (a) write a short summary and (b) propose zero or more
     durable fact/preference candidates.
  2. For each candidate, dedup against existing memory.
  3. Every decision is logged to `memory_events`.
"""
from uuid import UUID

import numpy as np
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.models import Fact, Preference, MemoryEvent
from app.schemas import ExtractionResult, ExtractedCandidate
from app.embeddings import embed_text
from app.jsonutil import parse_json_payload
from app.llm import generate_text


EXTRACTION_SYSTEM_PROMPT = """You analyze a single dictation transcript and extract durable memory.

Output strict JSON matching this shape:
{
  "summary": "<1-2 sentence summary of what this dictation was about>",
  "candidates": [
    {
      "type": "fact" | "preference" | "none",
      "subject": "<short subject, e.g. 'manager', 'project codename'>",
      "value": "<the fact's value, e.g. 'Priya Nair'>",
      "category": "<'tone' | 'formatting' | 'signoff' | other short label>",
      "description": "<the preference, phrased generally>",
      "confidence": 0.0-1.0,
      "reason": "<one sentence on why this qualifies as durable>"
    }
  ]
}

Rules:
- Only extract something if it would plausibly still be true or useful weeks from now.
- Do NOT extract: one-off task details, transient moods, meeting logistics, speculative statements, anything true only "today".
- A fact is a concrete, checkable statement (names, numbers, identifiers, relationships).
- A preference is a recurring stylistic or behavioral pattern, not a one-time instruction.
- If nothing durable is present, return "candidates": [].
- Prefer under-extracting to over-extracting. Most dictations should produce 0-2 candidates.
- Return ONLY the JSON object, no other text.
"""


def run_extraction(transcript_text: str) -> ExtractionResult:
    """Single LLM call: summarize + propose candidates. Kept as one call
    (not two) to save cost/latency across ~500 records."""
    if not settings.GEMINI_API_KEY:
        snippet = (transcript_text or "").strip().replace("\n", " ")
        return ExtractionResult(summary=snippet[:280], candidates=[])

    raw = generate_text(
        f"Transcript:\n{transcript_text}",
        system=EXTRACTION_SYSTEM_PROMPT,
        model=settings.EXTRACTION_MODEL,
        max_tokens=1024,
    )
    try:
        data = parse_json_payload(raw)
        if not isinstance(data, dict):
            raise ValueError("extraction output was not an object")
        candidates = []
        for item in data.get("candidates") or []:
            try:
                candidates.append(ExtractedCandidate.model_validate(item))
            except ValidationError:
                continue
        summary = data.get("summary") or ""
        return ExtractionResult(summary=str(summary), candidates=candidates)
    except (ValueError, TypeError) as exc:
        snippet = (transcript_text or "").strip().replace("\n", " ")
        return ExtractionResult(summary=snippet[:280] or f"parse error: {exc}", candidates=[])


def _cosine_sim(a: list[float], b: list[float]) -> float:
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    return float(a.dot(b) / denom) if denom else 0.0


PREFERENCE_MERGE_THRESHOLD = 0.85


def upsert_fact(db: Session, user_id: UUID, episode_id: UUID, c: ExtractedCandidate):
    existing = db.execute(
        select(Fact).where(
            Fact.user_id == user_id,
            Fact.subject == c.subject,
            Fact.status == "active",
        )
    ).scalar_one_or_none()

    emb = embed_text(f"{c.subject}: {c.value}")

    if existing is None:
        fact = Fact(
            user_id=user_id, subject=c.subject, value=c.value,
            confidence=c.confidence, source_episode_ids=[episode_id],
            embedding=emb,
        )
        db.add(fact)
        db.flush()
        _log(db, user_id, episode_id, "created_fact", "facts", fact.id, c.reason, c)
        return fact, "created"

    if existing.value.strip().lower() == c.value.strip().lower():
        ids = list(existing.source_episode_ids or [])
        if episode_id not in ids:
            existing.source_episode_ids = ids + [episode_id]
            flag_modified(existing, "source_episode_ids")
        _log(db, user_id, episode_id, "reinforced_fact", "facts", existing.id, c.reason, c)
        return existing, "reinforced"

    existing.status = "superseded"
    new_fact = Fact(
        user_id=user_id, subject=c.subject, value=c.value,
        confidence=c.confidence, source_episode_ids=[episode_id],
        embedding=emb,
    )
    db.add(new_fact)
    db.flush()
    _log(db, user_id, episode_id, "updated_fact", "facts", new_fact.id,
         f"superseded {existing.id}: {c.reason}", c)
    return new_fact, "superseded_previous"


def upsert_preference(db: Session, user_id: UUID, episode_id: UUID, c: ExtractedCandidate):
    candidate_emb = embed_text(c.description)

    similar_prefs = db.execute(
        select(Preference).where(
            Preference.user_id == user_id,
            Preference.category == c.category,
            Preference.status == "active",
        )
    ).scalars().all()

    for pref in similar_prefs:
        if pref.embedding is None:
            continue
        if _cosine_sim(candidate_emb, list(pref.embedding)) >= PREFERENCE_MERGE_THRESHOLD:
            pref.evidence_count = (pref.evidence_count or 0) + 1
            pref.strength = min(1.0, (pref.strength or 0.0) + 0.1)
            ids = list(pref.source_episode_ids or [])
            if episode_id not in ids:
                pref.source_episode_ids = ids + [episode_id]
                flag_modified(pref, "source_episode_ids")
            _log(db, user_id, episode_id, "reinforced_preference", "preferences",
                 pref.id, c.reason, c)
            return pref, "reinforced"

    pref = Preference(
        user_id=user_id, category=c.category, description=c.description,
        strength=c.confidence, evidence_count=1,
        source_episode_ids=[episode_id], embedding=candidate_emb,
    )
    db.add(pref)
    db.flush()
    _log(db, user_id, episode_id, "created_preference", "preferences", pref.id, c.reason, c)
    return pref, "created"


def _log(db, user_id, episode_id, event_type, target_table, target_id, reason, candidate):
    db.add(MemoryEvent(
        user_id=user_id, episode_id=episode_id, event_type=event_type,
        target_table=target_table, target_id=target_id, reason=reason,
        raw_candidate=candidate.model_dump_json(),
    ))


def process_episode(db: Session, user_id: UUID, episode_id: UUID, transcript_text: str) -> tuple[ExtractionResult, dict[str, int]]:
    """Full extraction step for one episode: LLM call + dedup/upsert.
    Returns the extraction result and write counters for the ingest API."""
    result = run_extraction(transcript_text)
    stats = {"facts_created": 0, "preferences_created": 0, "facts_superseded": 0}

    for c in result.candidates:
        if c.type == "fact" and c.subject and c.value:
            _, action = upsert_fact(db, user_id, episode_id, c)
            if action == "created":
                stats["facts_created"] += 1
            elif action == "superseded_previous":
                stats["facts_created"] += 1
                stats["facts_superseded"] += 1
        elif c.type == "preference" and c.category and c.description:
            _, action = upsert_preference(db, user_id, episode_id, c)
            if action == "created":
                stats["preferences_created"] += 1
        else:
            _log(db, user_id, episode_id, "rejected", None, None,
                 c.reason or "no durable content", c)

    return result, stats


def capture_text(
    db: Session,
    user_id: UUID,
    text: str,
    source_app: str = "chat",
) -> tuple[Episode, dict[str, int]]:
    """Persist a live utterance as an episode and run extraction immediately."""
    from datetime import datetime, timezone
    from app.models import Episode
    from app.embeddings import embed_text

    cleaned = (text or "").strip()
    episode = Episode(
        user_id=user_id,
        occurred_at=datetime.now(timezone.utc),
        source_app=source_app,
        raw_asr=cleaned.lower(),
        formatted_text=cleaned,
        embedding=embed_text(cleaned),
    )
    db.add(episode)
    db.flush()
    result, stats = process_episode(db, user_id, episode.id, cleaned)
    episode.summary = result.summary
    db.commit()
    db.refresh(episode)
    return episode, stats
