"""Pydantic models for API request/response bodies and internal extraction
output. Kept separate from SQLAlchemy models (app/models.py) on purpose —
API shape and DB shape are allowed to diverge."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TranscriptRecord(BaseModel):
    """Shape of one corpus record — matches what the doc says an internal
    review corpus will contain: raw ASR, LLM-formatted output, metadata."""
    occurred_at: datetime
    source_app: Optional[str] = None
    raw_asr: str
    formatted_text: str


class IngestRequest(BaseModel):
    user_id: UUID
    records: list[TranscriptRecord]


class IngestResponse(BaseModel):
    episodes_created: int
    facts_created: int
    preferences_created: int
    facts_superseded: int


class ExtractedCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["fact", "preference", "none"]
    subject: Optional[str] = None
    value: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    candidates: list[ExtractedCandidate] = []


class HeyKiviRequest(BaseModel):
    user_id: UUID
    message: str


class HeyKiviResponse(BaseModel):
    answer: str
    cited_episode_ids: list[UUID] = []
    cited_fact_ids: list[UUID] = []
    cited_preference_ids: list[UUID] = []
    tool_trace: list[dict] = []
    latency_ms: float


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    source_app: Optional[str]
    formatted_text: str
    summary: Optional[str]


class FactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject: str
    value: str
    confidence: float
    status: str
    source_episode_ids: list[UUID]
    updated_at: datetime


class PreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: str
    description: str
    strength: float
    evidence_count: int
    status: str
    source_episode_ids: list[UUID]


class SessionOut(BaseModel):
    user_id: UUID


class FactWrite(BaseModel):
    user_id: UUID
    subject: str
    value: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class FactPatch(BaseModel):
    subject: Optional[str] = None
    value: Optional[str] = None
    status: Optional[str] = None


class PreferenceWrite(BaseModel):
    user_id: UUID
    category: str
    description: str
    strength: float = Field(default=0.7, ge=0.0, le=1.0)


class PreferencePatch(BaseModel):
    category: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class LiveNote(BaseModel):
    user_id: UUID
    text: str
    source_app: Optional[str] = "chat"
