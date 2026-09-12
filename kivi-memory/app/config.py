"""
Centralized configuration. Every module reads model names / keys from here
instead of calling os.getenv() directly — makes it trivial to swap models
from one place.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://kivi:kivi@localhost:5432/kivi_memory"
    )
    EXTRACTION_MODEL: str = os.getenv("EXTRACTION_MODEL", "gemini-3.6-flash")
    AGENT_MODEL: str = os.getenv("AGENT_MODEL", "gemini-3.6-flash")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "768"))

    @property
    def using_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


settings = Settings()
