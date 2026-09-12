"""
FastAPI entrypoint: ingest, Hey Kivi, live memory inspector, and SSE updates.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db, init_db
from app.models import Episode, Fact, Preference, now_utc
from app.schemas import (
    IngestRequest, IngestResponse, HeyKiviRequest, HeyKiviResponse,
    EpisodeOut, FactOut, PreferenceOut, SessionOut, FactWrite, FactPatch,
    PreferenceWrite, PreferencePatch, LiveNote,
)
from app.extraction import process_episode, capture_text, upsert_fact
from app.embeddings import embed_text
from app.agent import run_hey_kivi
from app.realtime import publish, subscribe, unsubscribe
from app.schemas import ExtractedCandidate


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Kivi Semantic Memory", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _notify(user_id: UUID, reason: str, extra: dict | None = None):
    payload = {"type": "memory_changed", "reason": reason, **(extra or {})}
    publish(user_id, payload)


@app.post("/session", response_model=SessionOut)
def create_session():
    return SessionOut(user_id=uuid.uuid4())


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, db: Session = Depends(get_db)):
    episodes_created = facts_created = prefs_created = facts_superseded = 0

    for rec in req.records:
        emb = embed_text(rec.formatted_text)
        episode = Episode(
            user_id=req.user_id, occurred_at=rec.occurred_at,
            source_app=rec.source_app, raw_asr=rec.raw_asr,
            formatted_text=rec.formatted_text, embedding=emb,
        )
        db.add(episode)
        db.flush()
        episodes_created += 1

        result, stats = process_episode(db, req.user_id, episode.id, rec.formatted_text)
        episode.summary = result.summary
        facts_created += stats["facts_created"]
        prefs_created += stats["preferences_created"]
        facts_superseded += stats["facts_superseded"]

    db.commit()
    _notify(req.user_id, "ingest", {
        "episodes_created": episodes_created,
        "facts_created": facts_created,
        "preferences_created": prefs_created,
        "facts_superseded": facts_superseded,
    })
    return IngestResponse(
        episodes_created=episodes_created,
        facts_created=facts_created,
        preferences_created=prefs_created,
        facts_superseded=facts_superseded,
    )


@app.post("/remember", response_model=IngestResponse)
def remember(note: LiveNote, db: Session = Depends(get_db)):
    if not note.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    _, stats = capture_text(db, note.user_id, note.text, note.source_app or "notes")
    extra = {"episodes_created": 1, **stats}
    _notify(note.user_id, "remember", extra)
    return IngestResponse(
        episodes_created=1,
        facts_created=stats["facts_created"],
        preferences_created=stats["preferences_created"],
        facts_superseded=stats["facts_superseded"],
    )


@app.post("/hey-kivi", response_model=HeyKiviResponse)
def hey_kivi(req: HeyKiviRequest, db: Session = Depends(get_db)):
    _, stats = capture_text(db, req.user_id, req.message, "chat")
    _notify(req.user_id, "chat_extract", {"episodes_created": 1, **stats})
    return run_hey_kivi(db, req.user_id, req.message)


@app.get("/memories/{user_id}/episodes", response_model=list[EpisodeOut])
def list_episodes(user_id: UUID, db: Session = Depends(get_db)):
    rows = db.query(Episode).filter(Episode.user_id == user_id).order_by(Episode.occurred_at.desc()).all()
    return rows


@app.get("/memories/{user_id}/facts", response_model=list[FactOut])
def list_facts(user_id: UUID, db: Session = Depends(get_db)):
    rows = db.query(Fact).filter(Fact.user_id == user_id).order_by(Fact.updated_at.desc()).all()
    return rows


@app.get("/memories/{user_id}/preferences", response_model=list[PreferenceOut])
def list_preferences(user_id: UUID, db: Session = Depends(get_db)):
    rows = db.query(Preference).filter(Preference.user_id == user_id).order_by(Preference.strength.desc()).all()
    return rows


@app.post("/memories/fact", response_model=FactOut)
def create_fact(body: FactWrite, db: Session = Depends(get_db)):
    episode = Episode(
        user_id=body.user_id,
        occurred_at=datetime.now(timezone.utc),
        source_app="user_edit",
        raw_asr=f"{body.subject}: {body.value}",
        formatted_text=f"{body.subject}: {body.value}",
        summary="User-created fact",
        embedding=embed_text(f"{body.subject}: {body.value}"),
    )
    db.add(episode)
    db.flush()
    fact, _ = upsert_fact(
        db, body.user_id, episode.id,
        ExtractedCandidate(
            type="fact", subject=body.subject.strip(), value=body.value.strip(),
            confidence=body.confidence, reason="created in the live inspector",
        ),
    )
    db.commit()
    db.refresh(fact)
    _notify(body.user_id, "fact_created", {"fact_id": str(fact.id)})
    return fact


@app.patch("/memories/fact/{fact_id}", response_model=FactOut)
def patch_fact(fact_id: UUID, body: FactPatch, db: Session = Depends(get_db)):
    fact = db.query(Fact).filter(Fact.id == fact_id).first()
    if not fact:
        raise HTTPException(status_code=404, detail="fact not found")

    if body.status == "rejected_by_user":
        fact.status = "rejected_by_user"
        fact.updated_at = now_utc()
        db.commit()
        db.refresh(fact)
        _notify(fact.user_id, "fact_removed", {"fact_id": str(fact.id)})
        return fact

    new_subject = (body.subject or fact.subject).strip()
    new_value = (body.value or fact.value).strip()
    if new_subject == fact.subject and new_value == fact.value:
        return fact

    episode = Episode(
        user_id=fact.user_id,
        occurred_at=datetime.now(timezone.utc),
        source_app="user_edit",
        raw_asr=f"{new_subject}: {new_value}",
        formatted_text=f"{new_subject}: {new_value}",
        summary="User-updated fact",
        embedding=embed_text(f"{new_subject}: {new_value}"),
    )
    db.add(episode)
    db.flush()
    updated, _ = upsert_fact(
        db, fact.user_id, episode.id,
        ExtractedCandidate(
            type="fact", subject=new_subject, value=new_value,
            confidence=max(fact.confidence or 0.5, 0.95),
            reason="edited in the live inspector",
        ),
    )
    db.commit()
    db.refresh(updated)
    _notify(fact.user_id, "fact_updated", {"fact_id": str(updated.id)})
    return updated


@app.post("/memories/preference", response_model=PreferenceOut)
def create_preference(body: PreferenceWrite, db: Session = Depends(get_db)):
    pref = Preference(
        user_id=body.user_id,
        category=body.category.strip(),
        description=body.description.strip(),
        strength=body.strength,
        evidence_count=1,
        source_episode_ids=[],
        embedding=embed_text(body.description),
        status="active",
    )
    db.add(pref)
    db.commit()
    db.refresh(pref)
    _notify(body.user_id, "preference_created", {"preference_id": str(pref.id)})
    return pref


@app.patch("/memories/preference/{preference_id}", response_model=PreferenceOut)
def patch_preference(preference_id: UUID, body: PreferencePatch, db: Session = Depends(get_db)):
    pref = db.query(Preference).filter(Preference.id == preference_id).first()
    if not pref:
        raise HTTPException(status_code=404, detail="preference not found")
    if body.category is not None:
        pref.category = body.category.strip()
    if body.description is not None:
        pref.description = body.description.strip()
        pref.embedding = embed_text(pref.description)
    if body.status is not None:
        pref.status = body.status
    pref.updated_at = now_utc()
    db.commit()
    db.refresh(pref)
    _notify(pref.user_id, "preference_updated", {"preference_id": str(pref.id)})
    return pref


@app.delete("/memories/fact/{fact_id}")
def delete_fact(fact_id: UUID, db: Session = Depends(get_db)):
    fact = db.query(Fact).filter(Fact.id == fact_id).first()
    if not fact:
        raise HTTPException(status_code=404, detail="fact not found")
    fact.status = "rejected_by_user"
    fact.updated_at = now_utc()
    db.commit()
    _notify(fact.user_id, "fact_removed", {"fact_id": str(fact.id)})
    return {"ok": True}


@app.delete("/memories/preference/{preference_id}")
def delete_preference(preference_id: UUID, db: Session = Depends(get_db)):
    pref = db.query(Preference).filter(Preference.id == preference_id).first()
    if not pref:
        raise HTTPException(status_code=404, detail="preference not found")
    pref.status = "rejected_by_user"
    pref.updated_at = now_utc()
    db.commit()
    _notify(pref.user_id, "preference_removed", {"preference_id": str(pref.id)})
    return {"ok": True}


@app.get("/events/{user_id}")
async def memory_events(user_id: UUID):
    queue = subscribe(user_id)

    async def stream():
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                payload = await queue.get()
                yield f"data: {json.dumps(payload, default=str)}\n\n"
        finally:
            unsubscribe(user_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/")
def chat_ui():
    return FileResponse(FRONTEND_DIR / "index.html")
