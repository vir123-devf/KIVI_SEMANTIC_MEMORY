"""
Thin wrapper around Gemini embeddings. Falls back to a deterministic local
embedding when GEMINI_API_KEY is unset so ingest/search still works in tests.
"""
import hashlib

import numpy as np

from app.config import settings

_client = None


def _local_embed(text: str) -> list[float]:
    digest = hashlib.sha256((text or "").encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big")
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(settings.EMBEDDING_DIM)
    norm = np.linalg.norm(vec)
    if norm:
        vec = vec / norm
    return vec.tolist()


def embed_text(text: str) -> list[float]:
    if not settings.GEMINI_API_KEY:
        return _local_embed(text)
    from app.llm import embed_texts
    return embed_texts([text])[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if not settings.GEMINI_API_KEY:
        return [_local_embed(t) for t in texts]
    from app.llm import embed_texts
    return embed_texts(texts)
