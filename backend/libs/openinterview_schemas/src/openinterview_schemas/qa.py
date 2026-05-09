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
    follow_up_axes: list[str] = Field(default_factory=list)


class QAGenerationRunOut(BaseModel):
    id: UUID
    status: str
    attempt: int = 1
    trigger: str = "manual"
    error: str | None = None
    meta: dict[str, Any] | None = None
    created_at: datetime
    completed_at: datetime | None = None


class QASetReviewRequest(BaseModel):
    review_status: str = Field(pattern="^(unreviewed|approved|needs_work|rejected)$")
    review_notes: str | None = None


class QASetOut(BaseModel):
    id: UUID
    project_id: UUID | None = None
    resume_id: UUID | None = None
    scope: str = "project"
    position: str
    level: str
    status: str
    total: int
    error: str | None = None
    review_status: str = "unreviewed"
    review_notes: str | None = None
    reviewed_at: datetime | None = None
    generation_run: QAGenerationRunOut | None = None
    created_at: datetime


class QASetDetail(QASetOut):
    items: list[QAItemOut] = Field(default_factory=list)


class GenerateQARequest(BaseModel):
    position: str = "swe_generic"
    levels: list[str] = Field(default_factory=lambda: ["junior", "mid", "senior", "tech_lead"])


class GenerateQAResponse(BaseModel):
    qa_set_ids: list[UUID]
