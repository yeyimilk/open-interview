from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class QAEvidence(BaseModel):
    rel_path: str
    start_line: int = 0
    end_line: int = 0
    snippet: str = ""


class QAItemOut(BaseModel):
    id: UUID
    category: str
    level: str
    question: str
    ideal_answer: str
    evidence: list[QAEvidence] = Field(default_factory=list)
    difficulty: int = 3
    tags: list[str] = Field(default_factory=list)


class QASetOut(BaseModel):
    id: UUID
    project_id: UUID
    position: str
    level: str
    status: str
    total: int
    error: str | None = None
    created_at: datetime


class QASetDetail(QASetOut):
    items: list[QAItemOut] = Field(default_factory=list)


class GenerateQARequest(BaseModel):
    position: str = "swe_generic"
    levels: list[str] = Field(default_factory=lambda: ["junior", "mid", "senior", "tech_lead"])


class GenerateQAResponse(BaseModel):
    qa_set_ids: list[UUID]
