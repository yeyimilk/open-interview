from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RetrievalSource(str, Enum):
    project = "project"
    common_kb = "common_kb"
    working_memory = "working_memory"
    episodic_memory = "episodic_memory"
    long_term_memory = "long_term_memory"
    resume = "resume"
    resume_claim = "resume_claim"
    qa = "qa"


class RetrievalPurpose(str, Enum):
    general_chat = "general_chat"
    mentor = "mentor"
    interviewer = "interviewer"
    qa_generation = "qa_generation"
    claim_mapping = "claim_mapping"


class Citation(BaseModel):
    source: RetrievalSource
    title: str | None = None
    project_id: UUID | None = None
    resume_id: UUID | None = None
    qa_set_id: UUID | None = None
    rel_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    id: str
    source: RetrievalSource
    text: str
    score: float = 0.0
    title: str | None = None
    citation: Citation
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrieveRequest(BaseModel):
    user_id: UUID
    query: str
    purpose: RetrievalPurpose = RetrievalPurpose.general_chat
    sources: list[RetrievalSource] | None = None
    session_id: UUID | None = None
    project_ids: list[UUID] | None = None
    resume_ids: list[UUID] | None = None
    qa_set_ids: list[UUID] | None = None
    space_keys: list[str] | None = None
    categories: list[str] | None = None
    company: str | None = None
    languages: list[str] | None = None
    top_k: int = 8
    per_source_top_k: dict[str, int] = Field(default_factory=dict)
    context_char_budget: int = 6000


class RetrieveResponse(BaseModel):
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    context_text: str = ""
    selected_sources: list[RetrievalSource] = Field(default_factory=list)
    total_chars: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)
