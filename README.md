# Kivi Semantic Memory

Hey Kivi is a **personal semantic memory** system for voice dictation. It remembers durable facts, writing preferences, and past dictations, then uses them only when the user asks — so answers can be grounded, inspectable, and corrected.

The runnable application lives in **[`kivi-memory/`](kivi-memory/)**. This README describes that product. Part One (positioning statement and vision document) is intentionally not generated here; add those yourself under `kivi-memory/docs/` before submission.

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
| API | FastAPI (`kivi-memory/app/main.py`) |
| UI | `kivi-memory/frontend/index.html` served at `/` |
| LLM + embeddings | Gemini (`gemini-3.6-flash`, `gemini-embedding-001`) |
| Store | Postgres + pgvector when available; SQLite fallback for local Windows |
| Eval | `kivi-memory/eval/run_eval.py` |

### Repository layout

```
kivi-memory/     Primary app (FastAPI, Gemini, live UI)
  app/           Extraction, retrieval, agent, API
  frontend/      Chat + live memory inspector
  corpus/        Generator + ingest for ~500 transcripts
  eval/          Question set and scoring harness
  tests/         Unit / API tests
scripts/         Deterministic corpus.jsonl (~500 lines) + older importer
backend/        Earlier SQLite scaffold (not the live Gemini app)
```

---

## Run

Requires Python 3.11+ and a Gemini API key.

```powershell
cd C:\Users\VIRENDRA\OneDrive\Desktop\kivi-memory\kivi-memory
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

**Optional Postgres** (from `kivi-memory/`):

```bash
docker compose up -d
alembic upgrade head
```

If Postgres is down, the API falls back to `kivi_memory.db`.

**Seed transcripts**

- Live app: `python -m corpus.generate_corpus` then `python -m corpus.ingest --file corpus/data/records.json` (from `kivi-memory/`).
- Root deterministic file: `scripts/corpus.jsonl` (~500 records), imported only by `scripts/import_corpus.py` against the older `/dictations` API — **not** loaded automatically by the live UI.

**Eval** (API running, user ingested):

```bash
python -m eval.run_eval --user-id <uuid>
```

```bash
python -m pytest tests -q
```

---

## Results

| Check | Result |
|---|---|
| Unit + API tests (`pytest tests` in `kivi-memory/`) | 9 passing (cosine math, fact create/reinforce/supersede, preference merge, health + ingest + fact patch) |
| Live smoke (Gemini) | Ingest extracted manager = Priya Nair and project = Falcon; Hey Kivi answered “Your manager is Priya Nair.” and cited the `get_facts` ID |
| Abstention (by design) | Eval q7/q8 must not invent a dog’s name or a competitor Series B |
| Contradiction (by design) | Q3 $2.4M then $2.6M: active fact is the later value; earlier row stays `superseded` |
| Inspector | Create / update / remove facts propagate over SSE |

The nine-question eval (`kivi-memory/eval/questions.json`) is the reviewer’s quantitative artifact. After ingest + `run_eval`, use **pass rate**, **grounding rate**, **correct abstention**, and **average latency** from `eval/results.json`. This README does not invent a harness pass rate that has not been produced.

Eval scoring: cited IDs must appear in the tool trace; expected keywords must appear when an answer exists; no-answer questions must abstain.

---

## Limitations

- Preference merge threshold (0.85 cosine) is untuned.
- `user_id` is trusted; no production auth.
- `polish_text` does not independently fact-check the rewrite.
- Chat-time extraction can over-capture if the model ignores “durable only.”
- Session id lives in `localStorage`; no login.
- SQLite ranks embeddings in Python; Postgres + pgvector is the scale path.
- Single LLM provider (Gemini) for extract, chat, and embed.
- Synthetic corpora will not match real ASR noise.

---

## AI use

Part Two (architecture, schema, extraction/retrieval/agent, live UI, migrations, corpus tooling, eval harness, and this README) was built **with generative-AI assistance**, which the assignment allows for the engineering work.

**Do not generate with AI:**

- positioning statement (≤ 100 words)
- product vision (≤ 600 words)

Place those in `kivi-memory/docs/`. They must be the author’s own reasoning.

| Role in the running product | Model |
|---|---|
| Extraction + Hey Kivi + polish | `gemini-3.6-flash` |
| Embeddings | `gemini-embedding-001` (768-d) |

Override with `.env` (`EXTRACTION_MODEL`, `AGENT_MODEL`, `EMBEDDING_MODEL`).
