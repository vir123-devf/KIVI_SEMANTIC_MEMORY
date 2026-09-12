# RUN.md

**Primary review method: local application (backend + local SQLite + static frontend).**

## 1. Required runtimes

- Python 3.11+

## 2. Required environment variables

Copy `.env.example` to `.env` and fill in:

- `ANTHROPIC_API_KEY` — required, used for extraction and orchestration.
- `KIVI_EXTRACTION_MODEL` — default `claude-haiku-4-5-20251001`
- `KIVI_ORCHESTRATION_MODEL` — default `claude-sonnet-4-6`
- `KIVI_DB_PATH` — default `./kivi.db`
- `KIVI_EMBEDDING_MODEL` — default `all-MiniLM-L6-v2` (downloaded on first run, no API key)

```
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY
```

## 3. Install dependencies

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Create, migrate, and seed the database

```
cd backend
python3 -c "from db import init_db; init_db('../schema.sql')"
```

This creates `kivi.db` (empty — no seed rows are inserted yet; corpus
import in step 7 populates it).

## 5. Start the backend

```
cd backend
uvicorn main:app --reload --port 8000
```

The frontend is served by the same process as static files.

## 6. Open the interface

http://localhost:8000/

Two tabs: **Hey Kivi** (chat) and **What Kivi Remembers** (memory
inspector — view/remove memories).

## 7. Import a corpus

Generate the included synthetic corpus (only needed once; `corpus.jsonl`
is also committed to the repo under `scripts/`):

```
cd scripts
python3 generate_corpus.py     # writes corpus.jsonl, ~500 records, seeded/deterministic
python3 import_corpus.py corpus.jsonl --base-url http://localhost:8000
```

Importing runs the full extraction pipeline per record (one Haiku call per
dictation) — expect roughly 1–2s/record, so ~10–15 minutes for 500 records.

**To import a different corpus** (e.g. the reviewer's internal one): place
it as JSONL with one record per line, each containing at minimum `ts`,
`raw_asr`, `llm_formatted` (see field-mapping notes and aliases accepted
in `scripts/import_corpus.py::normalize_record`), then run:

```
python3 import_corpus.py /path/to/other_corpus.jsonl --base-url http://localhost:8000
```

## 8. Primary interactions to try

In the Hey Kivi tab:
- *"Find the dictation I did around 5 PM yesterday in Slack and polish it for the meeting I'm walking into."*
- *"How do I usually sign off emails?"*
- *"Who's the design lead on the onboarding redesign, and what's our biggest client account called this quarter?"*
- *"Remember that I prefer to be called 'V' in casual Slack messages."*
- *"What did I say about my favorite restaurant in Lisbon?"* (should refuse — not in the corpus)

In the **What Kivi Remembers** tab: inspect and remove any memory.

## 9. Run the evaluation

```
cd eval
python3 run_eval.py --base-url http://localhost:8000
```

Writes `eval/report.json` — per-case pass/fail, tool calls made,
retrieved memory ids, reasoning summary, latency, token counts.

## 10. Where to inspect results and memory state

- `GET http://localhost:8000/memories` — all active memories
- `GET http://localhost:8000/memories/{id}/provenance` — source dictation(s)/span for a memory
- `GET http://localhost:8000/turns/{turn_id}` — full trace of a Hey Kivi turn (turn_id is returned in every `/hey_kivi` response)
- `eval/report.json` — evaluation results
- `kivi.db` — raw SQLite, inspectable with any SQLite client (`sqlite3 backend/kivi.db`)

## 11. Resetting the system

```
rm backend/kivi.db
cd backend && python3 -c "from db import init_db; init_db('../schema.sql')"
```

Then re-run step 7 to re-import a corpus.
