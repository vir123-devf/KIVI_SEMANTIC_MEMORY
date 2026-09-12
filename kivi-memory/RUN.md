# RUN.md

**Primary review method: local application (backend + frontend local, database via Docker).**

## 1. Required runtimes

- Python 3.11+
- Docker + Docker Compose (for Postgres + pgvector)
- No Node.js required — frontend is a static HTML file with vanilla JS

## 2. Required environment variables

Copy `.env.example` to `.env` and fill in:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://kivi:kivi@localhost:5432/kivi_memory   # default, matches docker-compose.yml
EXTRACTION_MODEL=claude-sonnet-4-6
AGENT_MODEL=claude-sonnet-4-6
EMBEDDING_MODEL=text-embedding-3-small
```

## 3. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Create, migrate, and seed the database

```bash
docker compose up -d            # starts Postgres + pgvector, wait ~5s for healthcheck
alembic upgrade head            # creates episodes / facts / preferences / memory_events tables
```

(Seed data is generated + ingested in steps 7-8 below, not baked into the migration.)

## 5. Start every required process

```bash
uvicorn app.main:app --reload --port 8000
```

Then open `frontend/index.html` directly in a browser (no server needed —
it's a static file making fetch calls to `http://localhost:8000`).

## 6. URL / interface to open

- API: `http://localhost:8000` (docs at `http://localhost:8000/docs`)
- Frontend: open `frontend/index.html` in any browser

## 7. Generate the corpus (~500 synthetic records)

```bash
python -m corpus.generate_corpus
```
Writes `corpus/data/records.json`. Takes a few minutes (batched LLM calls).
A corpus is already committed in this repo under `corpus/data/records.json`
if you'd rather skip regenerating it.

## 8. Primary interactions to try

```bash
python -m corpus.ingest --file corpus/data/records.json
```
This prints a `user_id` — copy it. Paste that `user_id` into the frontend's
top bar and click "Load", then try in the chat box:

- "Who is my manager?"
- "What's our Q3 revenue target?"
- "Find a dictation I did in Slack and polish it for a meeting I'm walking into."
- "What is my dog's name?" (should abstain — not in corpus)

Use the Memory Inspector panel (Facts / Preferences / Episodes tabs) to see
exactly what was extracted, with the ability to remove any item.

## 9. Exact command to run the eval

```bash
python -m eval.run_eval --user-id <the-uuid-printed-by-ingest.py>
```
Writes `eval/results.json` — per-question answer, full tool trace, citation
IDs, grounding check, latency.

## 10. Importing another corpus

Any JSON file matching this shape works with the same ingest command:
```json
[
  {
    "occurred_at": "2026-06-01T09:15:00Z",
    "source_app": "slack",
    "raw_asr": "raw lowercase speech to text",
    "formatted_text": "Properly formatted version."
  }
]
```
```bash
python -m corpus.ingest --file path/to/other_corpus.json --user-id <optional-existing-uuid>
```
Omit `--user-id` to ingest as a fresh user.

## 11. Where results and memory state can be inspected

- `eval/results.json` — full eval output after running step 9
- Frontend Memory Inspector — live facts/preferences/episodes per user
- `GET /memories/{user_id}/facts` / `/preferences` / `/episodes` — raw API
- `memory_events` table (via any Postgres client, e.g. `docker exec -it <container> psql -U kivi -d kivi_memory`) — full audit log of every extraction decision including rejections

## 12. Resetting the system

```bash
docker compose down -v      # drops the Postgres volume entirely
docker compose up -d
alembic upgrade head        # recreate empty tables
```
