from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectOut(BaseModel):
    id: UUID
    name: str
    source_type: str
    status: str
    summary: str | None
    created_at: datetime


class ProjectDetail(ProjectOut):
    architecture: Any | None = None
    interesting_decisions: Any | None = None


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class IngestRunOut(BaseModel):
    id: UUID
    kind: str
    status: str
    step: str | None
    progress: int
    error: str | None
    project_id: UUID | None
    resume_id: UUID | None
    created_at: datetime


class ProjectFileOut(BaseModel):
    id: UUID
    rel_path: str
    language: str | None
    bytes: int
    summary: str | None


class ProjectDiagramOut(BaseModel):
    id: UUID
    name: str
    kind: str
    mermaid: str
