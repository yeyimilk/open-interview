from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CommonKBSpaceCreate(BaseModel):
    key: str
    name: str
    description: str | None = None
    enabled: bool = True


class CommonKBSpaceOut(BaseModel):
    id: UUID
    key: str
    name: str
    description: str | None = None
    enabled: bool
    created_at: datetime


class CommonKBSourceCreate(BaseModel):
    space_key: str
    key: str
    name: str
    source_type: str = "upload"
    base_url: str | None = None
    license: str | None = None
    allowed_use: dict[str, Any] = Field(default_factory=lambda: {"store_text": True})


class CommonKBSourceUpdate(BaseModel):
    name: str | None = None
    source_type: str | None = None
    base_url: str | None = None
    license: str | None = None
    allowed_use: dict[str, Any] | None = None
    refresh_status: str | None = None


class CommonKBSourceOut(BaseModel):
    id: UUID
    space_id: UUID
    key: str
    name: str
    source_type: str
    base_url: str | None = None
    license: str | None = None
    allowed_use: dict[str, Any] | None = None
    refresh_status: str
    last_error: str | None = None
    created_at: datetime


class CommonKBDocumentOut(BaseModel):
    id: UUID
    space_id: UUID
    source_id: UUID | None = None
    title: str
    filename: str | None = None
    content_type: str | None = None
    blob_path: str | None = None
    canonical_url: str | None = None
    content_hash: str | None = None
    status: str
    error: str | None = None
    meta: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    create_embeddings: bool = True
    created_at: datetime


class CommonKBItemCreate(BaseModel):
    space_key: str
    source_id: UUID | None = None
    document_id: UUID | None = None
    item_type: str
    category: str
    title: str
    question: str | None = None
    answer_outline: str | None = None
    content: str | None = None
    difficulty: int = 3
    role_family: str | None = None
    level: str | None = None
    company: str | None = None
    language: str | None = None
    provenance: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    status: str = "ready"


class CommonKBItemUpdate(BaseModel):
    item_type: str | None = None
    category: str | None = None
    title: str | None = None
    question: str | None = None
    answer_outline: str | None = None
    content: str | None = None
    difficulty: int | None = None
    role_family: str | None = None
    level: str | None = None
    company: str | None = None
    language: str | None = None
    provenance: dict[str, Any] | None = None
    tags: list[str] | None = None
    status: str | None = None


class CommonKBItemOut(BaseModel):
    id: UUID
    space_id: UUID
    source_id: UUID | None = None
    document_id: UUID | None = None
    item_type: str
    category: str
    title: str
    question: str | None = None
    answer_outline: str | None = None
    content: str | None = None
    difficulty: int
    role_family: str | None = None
    level: str | None = None
    company: str | None = None
    language: str | None = None
    provenance: dict[str, Any] | None = None
    status: str
    version: int
    tags: list[str] = Field(default_factory=list)
    created_at: datetime


class CompanyInterviewProfileOut(BaseModel):
    id: UUID
    company_key: str
    company: str
    role_family: str | None = None
    category_weights: dict[str, float] | None = None
    language_preferences: list[str] | None = None
    round_patterns: list[dict[str, Any]] | None = None
    confidence: float
    source_refs: list[dict[str, Any]] | None = None
    item_count: int
    created_at: datetime


class InterviewPreferenceIn(BaseModel):
    target_company: str | None = None
    category_weights: dict[str, float] | None = None
    languages: list[str] = Field(default_factory=list)
    interview_style: str | None = None
    include_company_style: bool = True


class InterviewPreferenceOut(InterviewPreferenceIn):
    id: UUID | None = None
    user_id: UUID | None = None
    created_at: datetime | None = None


class InterviewSessionPreferences(BaseModel):
    category_weights: dict[str, float] | None = None
    languages: list[str] = Field(default_factory=list)
    include_company_style: bool = True
