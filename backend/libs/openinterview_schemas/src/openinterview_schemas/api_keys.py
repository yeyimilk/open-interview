from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateApiKeyRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=128)
    plaintext: str = Field(min_length=1, max_length=4096)


class ApiKeyOut(BaseModel):
    id: UUID
    provider: str
    label: str
    created_at: datetime
