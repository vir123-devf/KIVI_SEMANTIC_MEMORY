"""
Unit tests for extraction helpers and upsert logic.

Run: pytest tests/
"""
import uuid
from datetime import datetime, timezone

from app.db import Base, engine, SessionLocal, init_db
from app.extraction import _cosine_sim, process_episode, upsert_fact, upsert_preference
from app.jsonutil import parse_json_payload
from app.models import Episode, Fact
from app.schemas import ExtractedCandidate
from app.config import settings
from app.embeddings import embed_text


def test_cosine_sim_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine_sim(v, v) - 1.0) < 1e-6


def test_cosine_sim_orthogonal_vectors():
    a, b = [1.0, 0.0], [0.0, 1.0]
    assert abs(_cosine_sim(a, b) - 0.0) < 1e-6


def test_cosine_sim_opposite_vectors():
    a, b = [1.0, 0.0], [-1.0, 0.0]
    assert abs(_cosine_sim(a, b) - (-1.0)) < 1e-6


def test_parse_json_payload_strips_fences():
    payload = parse_json_payload("```json\n{\"answer\": \"hi\"}\n```")
    assert payload["answer"] == "hi"


def test_local_embed_is_deterministic():
    a = embed_text("hello kivi")
    b = embed_text("hello kivi")
    assert a == b
    assert len(a) == settings.EMBEDDING_DIM


def test_fact_create_reinforce_and_supersede():
    init_db()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user_id = uuid.uuid4()
        ep1 = uuid.uuid4()
        ep2 = uuid.uuid4()
        ep3 = uuid.uuid4()
        for eid in (ep1, ep2, ep3):
            db.add(Episode(
                id=eid, user_id=user_id,
                occurred_at=datetime.now(timezone.utc),
                raw_asr="x", formatted_text="x",
            ))
        db.flush()

        created, action = upsert_fact(
            db, user_id, ep1,
            ExtractedCandidate(type="fact", subject="manager", value="Priya Nair", confidence=0.9),
        )
        assert action == "created"

        _, action = upsert_fact(
            db, user_id, ep2,
            ExtractedCandidate(type="fact", subject="manager", value="priya nair", confidence=0.8),
        )
        assert action == "reinforced"

        new_fact, action = upsert_fact(
            db, user_id, ep3,
            ExtractedCandidate(type="fact", subject="manager", value="Alex Chen", confidence=0.95),
        )
        assert action == "superseded_previous"
        db.commit()

        active = db.query(Fact).filter(Fact.user_id == user_id, Fact.status == "active").all()
        superseded = db.query(Fact).filter(Fact.user_id == user_id, Fact.status == "superseded").all()
        assert len(active) == 1
        assert active[0].id == new_fact.id
        assert active[0].value == "Alex Chen"
        assert len(superseded) == 1
        assert superseded[0].id == created.id
    finally:
        db.close()


def test_preference_reinforces_similar_descriptions():
    init_db()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user_id = uuid.uuid4()
        ep1, ep2 = uuid.uuid4(), uuid.uuid4()
        for eid in (ep1, ep2):
            db.add(Episode(
                id=eid, user_id=user_id,
                occurred_at=datetime.now(timezone.utc),
                raw_asr="x", formatted_text="x",
            ))
        db.flush()

        pref, action = upsert_preference(
            db, user_id, ep1,
            ExtractedCandidate(
                type="preference", category="tone",
                description="prefers concise bullet points over prose", confidence=0.7,
            ),
        )
        assert action == "created"

        same, action = upsert_preference(
            db, user_id, ep2,
            ExtractedCandidate(
                type="preference", category="tone",
                description="prefers concise bullet points over prose", confidence=0.8,
            ),
        )
        assert action == "reinforced"
        assert same.id == pref.id
        assert same.evidence_count == 2
    finally:
        db.close()


def test_process_episode_without_api_key_does_not_crash():
    init_db()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user_id = uuid.uuid4()
        ep = Episode(
            user_id=user_id,
            occurred_at=datetime.now(timezone.utc),
            raw_asr="hello", formatted_text="Hello.",
        )
        db.add(ep)
        db.flush()
        result, stats = process_episode(db, user_id, ep.id, "Hello.")
        assert result.summary
        assert stats["facts_created"] == 0
    finally:
        db.close()
