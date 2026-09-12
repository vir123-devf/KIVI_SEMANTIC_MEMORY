"""
SQLAlchemy engine + session factory. Import `get_db` as a FastAPI dependency,
or `SessionLocal()` directly in scripts (ingestion, eval).

If Postgres is configured but unreachable (no Docker / no driver), fall back
to a local SQLite file so the API can still start.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

from app.config import settings

Base = declarative_base()


def _try_postgres(url: str) -> bool:
    try:
        probe = create_engine(url, pool_pre_ping=True)
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
        probe.dispose()
        return True
    except Exception:
        return False


def _resolve_url() -> str:
    url = settings.DATABASE_URL
    if url.startswith("sqlite"):
        return url
    if _try_postgres(url):
        return url
    fallback = "sqlite:///./kivi_memory.db"
    print(
        f"Postgres is not available ({url}). Falling back to {fallback}. "
        "Start Docker Postgres (see RUN.md) for pgvector production mode."
    )
    settings.DATABASE_URL = fallback
    return fallback


DATABASE_URL = _resolve_url()


def _make_engine(url: str):
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            return create_engine(
                "sqlite://",
                connect_args=connect_args,
                poolclass=StaticPool,
            )
        return create_engine(url, connect_args=connect_args)
    return create_engine(url, pool_pre_ping=True)


engine = _make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    """Create tables when running on SQLite (Alembic owns Postgres schema)."""
    if settings.using_sqlite:
        from app import models  # noqa: F401
        Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yields a session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
