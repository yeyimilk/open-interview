from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ModelRole = Literal["chat", "embedding", "transcription", "voice-analysis"]


class ProviderOverride(BaseModel):
    """Inline override that core threads into gateway requests.

    When present, the gateway service skips its catalog lookup and uses the
    triple verbatim. The user's API key for ``provider`` is still resolved
    via the existing key resolver."""

    provider: str
    endpoint: str
    model_id: str


class ModelPreferenceOut(BaseModel):
    role: ModelRole
    provider: str
    endpoint: str
    model_id: str
    updated_at: datetime | None = None


class UpdateModelPreferenceRequest(BaseModel):
    provider: str
    endpoint: str
    model_id: str


class ProviderModel(BaseModel):
    """One entry in the result of upstream ``GET /v1/models``."""

    id: str
    owned_by: str | None = None
    created: int | None = None


class ProviderModelList(BaseModel):
    provider: str
    endpoint: str
    models: list[ProviderModel] = Field(default_factory=list)


class ProviderTestRequest(BaseModel):
    user_id: UUID
    role: ModelRole
    provider: str
    endpoint: str
    model_id: str


class ProviderTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None = None
