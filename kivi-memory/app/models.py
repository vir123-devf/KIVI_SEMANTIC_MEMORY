"""
Three first-class memory tables (episodic / factual / preference) instead of
one generic `memories` blob — see README for the reasoning. Plus a
`memory_events` audit log so every create/update/reject is inspectable.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Float, DateTime, ForeignKey, Integer, JSON, TypeDecorator,
)
from sqlalchemy.types import Uuid

from app.db import Base
from app.config import settings


class UuidList(TypeDecorator):
    """JSON list of UUID strings. Always exposes list[uuid.UUID] in Python."""
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return []
        return [str(v) for v in value]

    def process_result_value(self, value, dialect):
        if not value:
            return []
        return [v if isinstance(v, uuid.UUID) else uuid.UUID(str(v)) for v in value]


class EmbeddingCol(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector
            return dialect.type_descriptor(Vector(settings.EMBEDDING_DIM))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return list(value)


def uuid_col():
    return Column(Uuid, primary_key=True, default=uuid.uuid4)


def now_utc():
    return datetime.now(timezone.utc)


class Episode(Base):
    """One row per dictation event. Append-only — never edited or deleted
    by the extraction pipeline. This is the ground truth everything else
    derives from."""
    __tablename__ = "episodes"

    id = uuid_col()
    user_id = Column(Uuid, nullable=False, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
    source_app = Column(String, index=True)
    raw_asr = Column(Text, nullable=False)
    formatted_text = Column(Text, nullable=False)
    summary = Column(Text)
    embedding = Column(EmbeddingCol)
    created_at = Column(DateTime(timezone=True), default=now_utc)


class Fact(Base):
    """Atomic durable fact. Contradictions never overwrite silently — the old
    row is marked 'superseded' and a new 'active' row is inserted."""
    __tablename__ = "facts"

    id = uuid_col()
    user_id = Column(Uuid, nullable=False, index=True)
    subject = Column(String, nullable=False, index=True)
    value = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    status = Column(String, default="active")
    source_episode_ids = Column(UuidList, nullable=False)
    embedding = Column(EmbeddingCol)
    created_at = Column(DateTime(timezone=True), default=now_utc)
    updated_at = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Preference(Base):
    """A stylistic/behavioral pattern, e.g. category='tone'."""
    __tablename__ = "preferences"

    id = uuid_col()
    user_id = Column(Uuid, nullable=False, index=True)
    category = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=False)
    strength = Column(Float, nullable=False, default=0.5)
    evidence_count = Column(Integer, default=1)
    source_episode_ids = Column(UuidList, nullable=False)
    status = Column(String, default="active")
    embedding = Column(EmbeddingCol)
    created_at = Column(DateTime(timezone=True), default=now_utc)
    updated_at = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class MemoryEvent(Base):
    """Audit log: every extraction decision, including rejections."""
    __tablename__ = "memory_events"

    id = uuid_col()
    user_id = Column(Uuid, nullable=False, index=True)
    episode_id = Column(Uuid, ForeignKey("episodes.id"), nullable=False)
    event_type = Column(String, nullable=False)
    target_table = Column(String)
    target_id = Column(Uuid)
    reason = Column(Text)
    raw_candidate = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now_utc)
