from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ResumeOut(BaseModel):
    id: UUID
    original_filename: str
    content_type: str
    created_at: datetime


class ResumeDetail(ResumeOut):
    text: str | None
    parsed: Any | None


class ClaimMappingOut(BaseModel):
    id: UUID
    claim: str
    project_id: UUID | None
    grounding: Any | None
    confidence: int
