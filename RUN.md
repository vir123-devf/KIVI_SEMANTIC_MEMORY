# RUN.md

**Primary review method:** the FastAPI + Gemini app in **`kivi-memory/`** (live chat UI at `/`). SQLite by default; Postgres + pgvector optional.

Demo: [https://www.youtube.com/watch?v=VghEaDrttvo](https://www.youtube.com/watch?v=VghEaDrttvo)

---

## 1. Required runtimes

- Python 3.11+ (verified on 3.14)
- Gemini API key
- No Node.js
- Docker optional (Postgres only)

---

## 2. Environment

```powershell
cd kivi-memory
copy .env.example .env
```

```
GEMINI_API_KEY=your_key_here
EXTRACTION_MODEL=gemini-3.6-flash
AGENT_MODEL=gemini-3.6-flash
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIM=768
DATABASE_URL=sqlite:///./kivi_memory.db
```

Postgres (matches `kivi-memory/docker-compose.yml`):

```
DATABASE_URL=postgresql://kivi:kivi@localhost:5432/kivi_memory
```

---

## 3. Install

```powershell
cd kivi-memory
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

On Windows, skip `.\venv\Scripts\activate` if PowerShell blocks scripts. Use `.\venv\Scripts\python.exe` instead.

---

## 4. Database

SQLite is created automatically on API start (`kivi_memory.db`).

Optional:

```powershell
cd kivi-memory
docker compose up -d
.\venv\Scripts\python.exe -m alembic upgrade head
```

---

## 5. Start

```powershell
cd kivi-memory
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

---

## 6. Open

| What | URL |
| --- | --- |
| Chat + live memory | **http://127.0.0.1:8000/** |
| API docs | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/health |

Header should read **live**. Session `user_id` is stored in the browser; no UUID paste required.

---

## 7. Try these

- `My manager is Priya Nair` → fact appears in Live memory
- `Who is my manager?` → cited answer
- Edit a fact → **Update** (supersede, keep history)
- `What is my dog's name?` → abstain
- **Remember a note** to extract without the agent

---

## 8. Optional corpus (~500 records)

From `kivi-memory/`:

```powershell
.\venv\Scripts\python.exe -m corpus.generate_corpus
.\venv\Scripts\python.exe -m corpus.ingest --file corpus/data/records.json
```

Root `scripts/corpus.jsonl` is **not** used by this app (older `/dictations` importer only).

---

## 9. Tests and eval

```powershell
cd kivi-memory
.\venv\Scripts\python.exe -m pytest tests -q
.\venv\Scripts\python.exe -m eval.run_eval --user-id <uuid>
```

Eval writes `kivi-memory/eval/results.json`. API must be running.

---

## 10. Inspect memory

- UI: Facts / Preferences / Episodes
- `GET /memories/{user_id}/facts` (also `/preferences`, `/episodes`)
- `GET /events/{user_id}` — live SSE
- SQLite file: `kivi-memory/kivi_memory.db`

---

## 11. Reset

```powershell
# stop uvicorn, then:
del kivi-memory\kivi_memory.db
```

Restart uvicorn. Clear browser `localStorage` key `kivi_user_id` for a new session.

Postgres:

```powershell
cd kivi-memory
docker compose down -v
docker compose up -d
.\venv\Scripts\python.exe -m alembic upgrade head
```
