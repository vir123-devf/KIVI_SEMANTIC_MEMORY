-- Kivi semantic memory — schema
-- SQLite. Run via scripts/init_db.py (executes this file).

PRAGMA foreign_keys = ON;

-- Raw dictation records (regular dictation mode; untouched by memory logic).
CREATE TABLE IF NOT EXISTS dictations (
    id              TEXT PRIMARY KEY,          -- uuid
    ts              TEXT NOT NULL,              -- ISO8601 timestamp
    app_context     TEXT,                       -- e.g. "Slack", "Gmail", "Notion"
    raw_asr         TEXT NOT NULL,               -- raw speech-to-text output
    llm_formatted   TEXT NOT NULL,               -- Kivi-styled written output
    meta            TEXT                         -- JSON blob: extra fields from corpus
);

-- Durable + episodic memory store.
-- kind: 'fact' | 'preference' | 'episodic'
-- status: 'active' | 'superseded' | 'rejected'
CREATE TABLE IF NOT EXISTS memories (
    id              TEXT PRIMARY KEY,          -- uuid
    kind            TEXT NOT NULL,
    content         TEXT NOT NULL,               -- normalized natural-language statement
    confidence      REAL NOT NULL DEFAULT 0.7,
    status          TEXT NOT NULL DEFAULT 'active',
    superseded_by   TEXT,                        -- memory id, if status='superseded'
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    embedding       BLOB NOT NULL,               -- float32 vector, serialized
    FOREIGN KEY (superseded_by) REFERENCES memories(id)
);

-- Which dictation(s) a memory was extracted from / last touched by.
CREATE TABLE IF NOT EXISTS memory_provenance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id       TEXT NOT NULL,
    dictation_id    TEXT,                        -- nullable: explicit "remember" has no dictation
    extracted_span  TEXT,                        -- the substring/paraphrase that justified the memory
    extraction_method TEXT NOT NULL,              -- 'llm_extraction' | 'explicit_user' | 'merge'
    FOREIGN KEY (memory_id) REFERENCES memories(id),
    FOREIGN KEY (dictation_id) REFERENCES dictations(id)
);

-- Every Hey Kivi turn, logged for inspection/eval.
CREATE TABLE IF NOT EXISTS hey_kivi_turns (
    id              TEXT PRIMARY KEY,
    ts              TEXT NOT NULL,
    query_text      TEXT NOT NULL,
    tool_calls      TEXT,                        -- JSON: [{name, input, output}]
    retrieved_memory_ids TEXT,                    -- JSON list
    response_text   TEXT,
    reasoning_note  TEXT,                         -- short explanation of what was used/why
    latency_ms      INTEGER,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    model_used      TEXT
);
