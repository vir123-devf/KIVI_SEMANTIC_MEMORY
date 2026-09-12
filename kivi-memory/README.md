# Kivi Semantic Memory

Hey Kivi is a **personal semantic memory** system for voice dictation. It remembers durable facts, writing preferences, and past dictations, then uses them only when the user asks — so answers can be grounded, inspectable, and corrected.

This repository is the **Part Two** engineering build (working product + eval). Part One (positioning statement and vision document) is intentionally not generated here; add those yourself under `docs/` before submission.

---

## Product

Kivi treats memory as three different things with different rules, not one generic “notes” blob.

| Memory | What it stores | Lifecycle |
|---|---|---|
| **Episodes** | One row per dictation or chat utterance (raw ASR + formatted text + embedding) | Append-only. Never overwritten. |
| **Facts** | Atomic durable statements (`subject` → `value`), e.g. manager = Priya Nair | Deduped by subject. A later contradiction **supersedes** the old row; history is kept. Users can edit or reject. |
| **Preferences** | Recurring style patterns (tone, formatting, sign-off) | Merged by category + embedding similarity; repeats **reinforce** strength instead of duplicating. |

**Hey Kivi** is the only surface that *reads* this memory. Ordinary dictation *writes* episodes and triggers extraction. The assistant must cite the episode / fact / preference IDs it used, and must abstain when tools return nothing.

The live UI is a real session (browser-persisted `user_id`), not a hardcoded demo user. Chat, notes, and inspector edits all write through the same extraction and supersede path, and the inspector updates over a live event stream.

---

## Use cases

The product is scoped to three jobs that are useful on their own:

1. **Episodic recall** — “Find the dictation I did in Slack around 5pm.” Filter by time and source app first, then rank by semantic similarity. Pure vector search cannot do this query well.
2. **Fact grounding** — “Who is my manager?” / “What’s the Q3 target?” Answer only from active facts. If the user later says the target changed, the old fact is superseded, not silently overwritten.
3. **Preference-aware polish** — “Polish this Slack note for the meeting I’m walking into.” Load stored preferences, then rewrite.

Out of scope on purpose: sentiment, relationship graphs, goal inference, org-wide memory, and auto-applying style to every dictation. Those are easy to hallucinate and are not required for the three jobs above.

Try in the UI:

- “My manager is Priya Nair.” → appears as a live fact.
- “Who is my manager?” → grounded answer with a fact citation.
- Edit the fact to another name → old row superseded, next answer uses the new value.
- “What is my dog’s name?” → should refuse to invent an answer.

---

## Architecture

```
dictation / chat / note
        │
        ▼
   episode (append-only) + embedding
        │
        ▼
   Gemini extraction (conservative JSON)
        │
        ├── facts        (subject match → create | reinforce | supersede)
        ├── preferences  (category + cosine ≥ 0.85 → reinforce)
        └── memory_events (audit: created, updated, rejected)
        │
        ▼
Hey Kivi  ── tool loop ──►  search_episodes
                            get_facts
                            get_preferences
                            polish_text
        │
        ▼
JSON answer + cited IDs     SSE ──► live inspector
```

**Why three tables.** Episodes, facts, and preferences do not share a lifecycle. One polymorphic `memories` table would push type-specific rules into every reader.

**Why hybrid retrieval.** “Around 5pm yesterday in Slack” is a filter, then a rank. Embeddings alone pick the wrong episode.

**Why citations are mandatory.** Forced JSON with IDs makes “what memory produced this answer?” and “did it invent an ID?” checkable in `eval/run_eval.py`.

**Why supersede, not overwrite.** `facts.status` moves `active` → `superseded`. Engineers (and the user) can see when the system’s belief changed.

**Live path.** `POST /hey-kivi` first captures the user turn as an episode and extracts; then the agent answers with tools. `POST /remember` is the same extraction without the agent. Inspector `PATCH` uses the same upsert. `GET /events/{user_id}` (SSE) notifies the UI.

### Stack

| Layer | Choice |
|---|---|
| API | FastAPI (`app/main.py`) |
| UI | Single-page `frontend/index.html` served at `/` |
| LLM + embeddings | Gemini (`gemini-3.6-flash`, `gemini-embedding-001`) |
| Store | Postgres + pgvector when available; SQLite fallback for local Windows |
| Migrations | Alembic (`migrations/versions/0001_init.py`) |
| Eval | `eval/run_eval.py` + `eval/questions.json` |

### Layout

```
app/           API, extraction, retrieval, agent, Gemini client
frontend/      Live chat + memory inspector
corpus/        Generator + ingest for ~500 synthetic transcripts
eval/          Grounded question set and scoring harness
tests/         Extraction / upsert / API tests
migrations/    Postgres schema
```

---

## Run

Requires Python 3.11+ (this repo was run on 3.14) and a Gemini API key in `.env`.

```powershell
cd kivi-memory
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

Set `GEMINI_API_KEY` in `.env`. Then:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Open **http://127.0.0.1:8000/**  
API docs: http://127.0.0.1:8000/docs

On Windows PowerShell, `.\venv\Scripts\activate` may fail if script execution is disabled. Calling `.\venv\Scripts\python.exe` directly avoids that.

**Optional Postgres**

```bash
docker compose up -d
alembic upgrade head
```

If Postgres is down, the API falls back to `kivi_memory.db`.

**Seed ~500 transcripts (optional)**

```bash
python -m corpus.generate_corpus          # writes corpus/data/records.json
python -m corpus.ingest --file corpus/data/records.json
```

A separate, deterministic corpus also lives at the repo root as `scripts/corpus.jsonl` (for the earlier `/dictations` importer). The live app ingest path is `corpus/data/records.json`.

**Eval** (API must be running, user must be ingested):

```bash
python -m eval.run_eval --user-id <uuid>
```

Writes `eval/results.json` (per-question answer, tool trace, citation IDs, grounding, latency).

```bash
python -m pytest tests -q
```

---

## Results

What is mechanically true today:

| Check | Result |
|---|---|
| Unit + API tests (`pytest tests`) | 9 passing (cosine math, fact create/reinforce/supersede, preference merge, health + ingest + fact patch) |
| Live smoke (Gemini) | Ingest extracted manager = Priya Nair and project = Falcon; Hey Kivi answered “Your manager is Priya Nair.” and cited the fact ID returned by `get_facts` |
| Abstention (by design) | Eval cases q7/q8 (“dog’s name”, invented competitor funding) must refuse; the agent is instructed to use tools only |
| Contradiction (by design) | Q3 target $2.4M then $2.6M: active fact should be $2.6M; old row remains `superseded` |
| Inspector | Create / update / remove facts propagate over SSE without a page reload |

The full nine-question eval against a 500-record ingest (`eval/questions.json`) is the reviewer’s primary quantitative artifact. After ingest + `run_eval`, report **pass rate**, **grounding rate**, **correct abstention**, and **average latency** from `eval/results.json`. This README does not invent a pass rate that has not been written by that harness.

Eval scoring:

- **Grounded** — every cited ID appeared in the tool trace.
- **Keyword match** — expected substring present (Priya, Falcon, 9:30, 2.6, Best Vir, direct).
- **Abstention** — for no-answer items, the reply admits it does not know.

---

## Limitations

- **Preference merge (0.85 cosine)** is a heuristic, not fit on labeled duplicates.
- **`user_id` is trusted.** Fine for a take-home; not multi-tenant production.
- **`polish_text` does not independently fact-check** the rewrite against the source note.
- **Chat extraction** can over-capture if the model ignores “durable only” instructions; the prompt is conservative, not perfect.
- **No login.** Session id is stored in `localStorage`.
- **SQLite fallback** stores embeddings as JSON and ranks in Python. Postgres + pgvector is the intended scale path; IVFFlat still needs retuning beyond a few thousand rows.
- **Gemini-only.** Extraction, tools, and embeddings share one provider; an outage or quota limit hits every path.
- **Corpus generation** is synthetic. Retrieval quality on real dictation noise will differ.

---

## AI use

Part Two of this project (architecture, schema, extraction/retrieval/agent, live UI, migrations, corpus tooling, eval harness, and this README) was built **with generative-AI assistance**, which the assignment allows for the engineering work.

**Not in scope for AI (do not generate these):**

- `docs/positioning-statement.md` (≤ 100 words)
- `docs/product-vision.md` (≤ 600 words)

Those must be the author’s own reasoning. A borrowed position is unlikely to survive a follow-up interview.

Models used in the **running product**:

| Role | Model |
|---|---|
| Extraction + Hey Kivi + polish | `gemini-3.6-flash` |
| Embeddings | `gemini-embedding-001` (768-d) |

Override via `.env` (`EXTRACTION_MODEL`, `AGENT_MODEL`, `EMBEDDING_MODEL`) without code changes.

---

## License / intent

Take-home reference implementation for a voice-assistant semantic memory, not a production identity or compliance system.
