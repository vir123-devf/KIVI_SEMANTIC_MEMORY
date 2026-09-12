import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from db import get_conn, init_db, new_id, now_iso
import memory as mem
from orchestrate import handle_turn

app = FastAPI(title="Kivi Semantic Memory")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Dictation(BaseModel):
    ts: str
    app_context: str | None = None
    raw_asr: str
    llm_formatted: str
    meta: dict | None = None


class HeyKiviQuery(BaseModel):
    query: str


@app.on_event("startup")
def startup():
    if not os.path.exists(os.environ.get("KIVI_DB_PATH", "./kivi.db")):
        init_db("../schema.sql" if os.path.basename(os.getcwd()) == "backend" else "schema.sql")


@app.post("/dictations")
def ingest_dictation(d: Dictation):
    did = new_id()
    conn = get_conn()
    conn.execute(
        "INSERT INTO dictations (id, ts, app_context, raw_asr, llm_formatted, meta) VALUES (?,?,?,?,?,?)",
        (did, d.ts, d.app_context, d.raw_asr, d.llm_formatted, json.dumps(d.meta or {})),
    )
    conn.commit()
    conn.close()
    memory_ids = mem.extract_and_store(did, d.llm_formatted)
    return {"dictation_id": did, "memories_created_or_updated": memory_ids}


@app.post("/hey_kivi")
def hey_kivi(q: HeyKiviQuery):
    return handle_turn(q.query)


@app.get("/memories")
def list_memories(kind: str | None = None, status: str = "active"):
    conn = get_conn()
    q = "SELECT id, kind, content, confidence, status, created_at, updated_at FROM memories WHERE status=?"
    params = [status]
    if kind:
        q += " AND kind=?"
        params.append(kind)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return {"memories": [dict(r) for r in rows]}


@app.get("/memories/{memory_id}/provenance")
def memory_provenance(memory_id: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT p.*, d.llm_formatted, d.ts as dictation_ts FROM memory_provenance p "
        "LEFT JOIN dictations d ON p.dictation_id = d.id WHERE p.memory_id=?", (memory_id,)
    ).fetchall()
    conn.close()
    if not rows:
        raise HTTPException(404, "not found")
    return {"provenance": [dict(r) for r in rows]}


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: str):
    conn = get_conn()
    conn.execute("UPDATE memories SET status='rejected', updated_at=? WHERE id=?", (now_iso(), memory_id))
    conn.commit()
    conn.close()
    return {"deleted": True}


@app.get("/turns/{turn_id}")
def get_turn(turn_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM hey_kivi_turns WHERE id=?", (turn_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "not found")
    return dict(row)


if os.path.isdir("../frontend"):
    app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
