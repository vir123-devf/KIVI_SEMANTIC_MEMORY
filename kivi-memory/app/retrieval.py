"""
Hybrid retrieval: structured filters (time range, source app) combined with
vector similarity. Pure embedding search alone fails the doc's own example
query -- "the dictation around 5pm yesterday in Slack" is a filter problem,
not a semantic-similarity problem. Filter first, rank within the filtered
set second.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Episode, Fact, Preference
from app.embeddings import embed_text
from app.extraction import _cosine_sim


def _rank_by_embedding(rows, query_emb: list[float], limit: int):
    def distance(row) -> float:
        emb = row.embedding
        if not emb:
            return 1.0
        return 1.0 - _cosine_sim(query_emb, list(emb))
    return sorted(rows, key=distance)[:limit]


def search_episodes(
    db: Session,
    user_id: UUID,
    query: str | None = None,
    time_start: datetime | None = None,
    time_end: datetime | None = None,
    source_app: str | None = None,
    limit: int = 5,
) -> list[Episode]:
    stmt = select(Episode).where(Episode.user_id == user_id)

    if time_start is not None:
        stmt = stmt.where(Episode.occurred_at >= time_start)
    if time_end is not None:
        stmt = stmt.where(Episode.occurred_at <= time_end)
    if source_app is not None:
        stmt = stmt.where(Episode.source_app == source_app)

    if query:
        q_emb = embed_text(query)
        rows = list(db.execute(stmt).scalars().all())
        return _rank_by_embedding(rows, q_emb, limit)

    stmt = stmt.order_by(Episode.occurred_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_facts(db: Session, user_id: UUID, subject_query: str | None = None, limit: int = 10) -> list[Fact]:
    stmt = select(Fact).where(Fact.user_id == user_id, Fact.status == "active")
    if subject_query:
        q_emb = embed_text(subject_query)
        rows = list(db.execute(stmt).scalars().all())
        return _rank_by_embedding(rows, q_emb, limit)
    stmt = stmt.order_by(Fact.updated_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_preferences(db: Session, user_id: UUID, category: str | None = None, limit: int = 10) -> list[Preference]:
    stmt = select(Preference).where(Preference.user_id == user_id, Preference.status == "active")
    if category:
        stmt = stmt.where(Preference.category == category)
    stmt = stmt.order_by(Preference.strength.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())
