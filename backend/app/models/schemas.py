"""Pydantic request/response models — every route validates against these."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    code: str
    message: str


class Envelope(BaseModel):
    """Every API response follows this shape, per architecture.md."""
    data: dict | list | None = None
    error: ErrorDetail | None = None


def ok(data: dict | list | None) -> dict:
    return {"data": data, "error": None}


def err(code: str, message: str) -> dict:
    return {"data": None, "error": {"code": code, "message": message}}


class CreateSessionRequest(BaseModel):
    user_label: str | None = None


class SessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    model_provider: str
    user_label: str | None = None

    model_config = ConfigDict(from_attributes=True)


class Citation(BaseModel):
    chunk_id: UUID
    episode_id: str
    episode_title: str | None = None
    source_url: str | None = None


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
    next_after: UUID | None = None


class MessageResponse(BaseModel):
    id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GenerateArtifactRequest(BaseModel):
    type: Literal["ship30_essay", "markdown", "html"]
    topic: str | None = None


class ArtifactResponse(BaseModel):
    id: UUID
    type: Literal["markdown", "html"]
    title: str | None = None
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModelConfigResponse(BaseModel):
    active_provider: Literal["ollama", "anthropic", "openai", "gemini"]
    available_providers: list[str]


class SetModelConfigRequest(BaseModel):
    provider: Literal["ollama", "anthropic", "openai", "gemini"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    ollama: bool
    active_provider: str
