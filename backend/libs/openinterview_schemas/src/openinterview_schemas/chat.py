from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChatSessionOut(BaseModel):
    id: UUID
    mode: str
    title: str | None = None
    project_id: UUID | None = None
    target: dict[str, Any] | None = None
    status: str
    turn_count: int
    created_at: datetime


class ChatMessageOut(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    meta: dict[str, Any] | None = None
    created_at: datetime


# ---------- Mentor ----------

class CreateMentorSessionRequest(BaseModel):
    project_id: UUID | None = None
    title: str | None = None


class SendMentorMessageRequest(BaseModel):
    content: str
    project_id: UUID | None = None


# ---------- Interviewer ----------

class CreateInterviewerSessionRequest(BaseModel):
    project_id: UUID
    position: str = "swe_generic"
    level: str = "mid"
    n_questions: int = 5


class SendInterviewerMessageRequest(BaseModel):
    content: str


class InterviewEvaluationOut(BaseModel):
    id: UUID
    session_id: UUID
    overall_score: float
    scores: dict[str, float] | None = None
    summary: str | None = None
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggested_practice: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
