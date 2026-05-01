from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from ..base import Base
from ._mixins import TimestampMixin, UUIDPKMixin


# Use JSONB on Postgres but JSON on SQLite (for tests)
JsonType = JSON().with_variant(JSONB(), "postgresql")


class Project(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # zip|git|folder
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    architecture: Mapped[Any] = mapped_column(JsonType, nullable=True)
    interesting_decisions: Mapped[Any] = mapped_column(JsonType, nullable=True)


class ProjectFile(UUIDPKMixin, TimestampMixin, Base):
    """Per-file summary + metadata (chunks live in the vector store)."""
    __tablename__ = "project_files"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bytes: Mapped[int] = mapped_column(default=0, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectDiagram(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "project_diagrams"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # component|sequence
    mermaid: Mapped[str] = mapped_column(Text, nullable=False)


class IngestRun(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "ingest_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # project|resume
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[int] = mapped_column(default=0, nullable=False)  # 0..100
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
