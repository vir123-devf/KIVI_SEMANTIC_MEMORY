"""
Thin data-access layer. SQLite for storage, sentence-transformers for
embeddings, cosine similarity computed in-process (fine at ~500-5,000 row
scale; if this needed to scale past that, swap in pgvector/sqlite-vec
without touching callers, since everything goes through the functions here).
"""
import os
import sqlite3
import struct
import uuid
import json
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

DB_PATH = os.environ.get("KIVI_DB_PATH", "./kivi.db")
EMBED_MODEL_NAME = os.environ.get("KIVI_EMBEDDING_MODEL", "all-MiniLM-L6-v2")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(schema_path: str = "schema.sql"):
    conn = get_conn()
    with open(schema_path, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


@lru_cache(maxsize=1)
def _embedder() -> SentenceTransformer:
    # Loaded once per process; local model, no network call at inference time.
    return SentenceTransformer(EMBED_MODEL_NAME)


def embed(text: str) -> np.ndarray:
    vec = _embedder().encode(text, normalize_embeddings=True)
    return vec.astype(np.float32)


def vec_to_blob(vec: np.ndarray) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec.tolist())


def blob_to_vec(blob: bytes) -> np.ndarray:
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-8
    return float(np.dot(a, b) / denom)
