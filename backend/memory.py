"""
The memory pipeline: extract -> dedup/merge -> store -> retrieve.

Design choices:
- Extraction is a strict allow-list task: the model is told what COUNTS as
  a memory (stable facts, preferences, or a one-line episodic summary of
  what happened) and told to emit nothing when a dictation contains none.
  This is where "what it deliberately ignores" lives - most dictations
  should produce zero or one memory, not a pile of inferences.
- Every candidate is checked against existing memories via embedding
  similarity before an LLM judge decides new vs. duplicate vs. update
  vs. contradiction (-> supersede). This keeps the store from accumulating
  near-duplicate facts every time a preference is restated.
- Retrieval blends embedding similarity with recency and type filtering
  rather than pure nearest-neighbor, since a stale preference that's since
  been superseded should not outrank a fresh, relevant one.
"""
import json
from datetime import datetime

from db import get_conn, embed, vec_to_blob, blob_to_vec, cosine, now_iso, new_id
from llm_client import call, extract_json, EXTRACTION_MODEL

EXTRACTION_SYSTEM = """You extract durable memory candidates from a single \
dictation. A memory is worth keeping only if it would still be useful days \
or weeks later. Output a JSON list (possibly empty) of objects:
{"kind": "fact"|"preference"|"episodic", "content": "<normalized statement, \
third person, e.g. 'Prefers bullet points for status updates'>", \
"confidence": <0-1>, "span": "<short quote/paraphrase of the source text \
that justifies this>"}

Rules:
- "fact": stable information about the person's work (project names, \
people, recurring terms). Not one-off details.
- "preference": a stated or clearly implied stylistic/behavioral preference \
that would generalize to future dictations.
- "episodic": ONLY when the dictation itself is a notable event worth \
recalling later (e.g. drafting something specific for a specific purpose). \
Summarize in one sentence: what was dictated, for what, in what context.
- If nothing in the dictation meets these bars, output [].
- Never infer facts about health, politics, or relationships from tone. \
Only extract what is explicitly stated or unambiguously implied by content.
- Output ONLY the JSON list, nothing else."""

DEDUP_SYSTEM = """You compare a NEW candidate memory against EXISTING \
similar memories and decide how to handle it. Output JSON:
{"action": "insert_new"|"duplicate_skip"|"update_existing"|"supersede", \
"target_id": "<id or null>", "merged_content": "<content to store, or \
null if skip>"}
- duplicate_skip: new candidate says the same thing as an existing memory.
- update_existing: new candidate refines/adds detail to an existing memory \
without contradicting it (e.g. "prefers bullet points" + "prefers bullet \
points, max 5" -> merged_content is the more specific version).
- supersede: new candidate CONTRADICTS an existing memory (e.g. preference \
changed). target_id is the memory being superseded.
- insert_new: genuinely new information.
Output ONLY the JSON object."""


def extract_and_store(dictation_id: str, text: str) -> list[str]:
    """Run extraction on one dictation, dedup each candidate, persist. Returns
    the list of memory ids that were newly created or updated."""
    resp, latency = call(
        model=EXTRACTION_MODEL,
        system=EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": text}],
        max_tokens=512,
    )
    raw = "".join(b.text for b in resp.content if b.type == "text")
    try:
        candidates = extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        candidates = []

    touched = []
    for cand in candidates:
        mem_id = _dedup_and_store(cand, dictation_id)
        if mem_id:
            touched.append(mem_id)
    return touched


def _dedup_and_store(cand: dict, dictation_id: str) -> str | None:
    content = cand.get("content", "").strip()
    if not content:
        return None
    kind = cand.get("kind", "fact")
    confidence = float(cand.get("confidence", 0.7))
    span = cand.get("span", "")

    vec = embed(content)
    similar = _similar_memories(vec, kind, top_k=3, min_score=0.75)

    if not similar:
        return _insert_memory(kind, content, confidence, vec, dictation_id, span, "llm_extraction")

    # Ask the model to adjudicate against the closest matches.
    existing_block = "\n".join(f"- id={m['id']}: {m['content']}" for m in similar)
    prompt = f"NEW: {content}\n\nEXISTING:\n{existing_block}"
    resp, _ = call(
        model=EXTRACTION_MODEL,
        system=DEDUP_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=256,
    )
    raw = "".join(b.text for b in resp.content if b.type == "text")
    try:
        decision = extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        decision = {"action": "insert_new"}

    action = decision.get("action", "insert_new")
    target_id = decision.get("target_id")

    if action == "duplicate_skip":
        return None
    if action == "update_existing" and target_id:
        merged = decision.get("merged_content") or content
        return _update_memory(target_id, merged, confidence, dictation_id, span)
    if action == "supersede" and target_id:
        new_id_ = _insert_memory(kind, content, confidence, vec, dictation_id, span, "llm_extraction")
        _supersede(target_id, new_id_)
        return new_id_
    return _insert_memory(kind, content, confidence, vec, dictation_id, span, "llm_extraction")


def _similar_memories(vec, kind: str, top_k: int, min_score: float) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, content, embedding FROM memories WHERE kind=? AND status='active'", (kind,)
    ).fetchall()
    conn.close()
    scored = []
    for r in rows:
        score = cosine(vec, blob_to_vec(r["embedding"]))
        if score >= min_score:
            scored.append({"id": r["id"], "content": r["content"], "score": score})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


def _insert_memory(kind, content, confidence, vec, dictation_id, span, method) -> str:
    mid = new_id()
    ts = now_iso()
    conn = get_conn()
    conn.execute(
        "INSERT INTO memories (id, kind, content, confidence, status, created_at, updated_at, embedding) "
        "VALUES (?,?,?,?,'active',?,?,?)",
        (mid, kind, content, confidence, ts, ts, vec_to_blob(vec)),
    )
    conn.execute(
        "INSERT INTO memory_provenance (memory_id, dictation_id, extracted_span, extraction_method) "
        "VALUES (?,?,?,?)",
        (mid, dictation_id, span, method),
    )
    conn.commit()
    conn.close()
    return mid


def _update_memory(mem_id, merged_content, confidence, dictation_id, span) -> str:
    vec = embed(merged_content)
    conn = get_conn()
    conn.execute(
        "UPDATE memories SET content=?, confidence=?, updated_at=?, embedding=? WHERE id=?",
        (merged_content, confidence, now_iso(), vec_to_blob(vec), mem_id),
    )
    conn.execute(
        "INSERT INTO memory_provenance (memory_id, dictation_id, extracted_span, extraction_method) "
        "VALUES (?,?,?,'merge')",
        (mem_id, dictation_id, span),
    )
    conn.commit()
    conn.close()
    return mem_id


def _supersede(old_id: str, new_id_: str):
    conn = get_conn()
    conn.execute(
        "UPDATE memories SET status='superseded', superseded_by=?, updated_at=? WHERE id=?",
        (new_id_, now_iso(), old_id),
    )
    conn.commit()
    conn.close()


def retrieve(query: str, kinds: list[str] | None = None, top_k: int = 6) -> list[dict]:
    """Hybrid retrieval: cosine similarity blended with a mild recency boost,
    active memories only. Returns provenance alongside each hit so callers
    (and the eval harness) can show why a memory was surfaced."""
    vec = embed(query)
    conn = get_conn()
    kind_filter = ""
    params: list = []
    if kinds:
        kind_filter = f"AND kind IN ({','.join('?' * len(kinds))})"
        params.extend(kinds)
    rows = conn.execute(
        f"SELECT * FROM memories WHERE status='active' {kind_filter}", params
    ).fetchall()

    scored = []
    now = datetime.fromisoformat(now_iso())
    for r in rows:
        sim = cosine(vec, blob_to_vec(r["embedding"]))
        age_days = max((now - datetime.fromisoformat(r["updated_at"])).days, 0)
        recency = 1.0 / (1.0 + age_days / 30.0)  # gentle decay, ~half-weight at 30 days
        score = 0.85 * sim + 0.15 * recency
        if sim < 0.2:  # floor: don't surface effectively-unrelated memories
            continue
        prov = conn.execute(
            "SELECT dictation_id, extracted_span, extraction_method FROM memory_provenance WHERE memory_id=? ORDER BY id DESC LIMIT 3",
            (r["id"],),
        ).fetchall()
        scored.append({
            "id": r["id"], "kind": r["kind"], "content": r["content"],
            "confidence": r["confidence"], "score": round(score, 3),
            "similarity": round(sim, 3),
            "provenance": [dict(p) for p in prov],
        })
    conn.close()
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]
