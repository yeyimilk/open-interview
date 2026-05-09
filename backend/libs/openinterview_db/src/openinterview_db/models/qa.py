from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from ..base import Base
from ._mixins import TimestampMixin, UUIDPKMixin

JsonType = JSON().with_variant(JSONB(), "postgresql")


class QASet(UUIDPKMixin, TimestampMixin, Base):
    """A bank of interview questions scoped to either a single project OR a
    resume. ``scope`` is the discriminator; exactly one of ``project_id`` /
    ``resume_id`` is set."""

    __tablename__ = "qa_sets"
    __table_args__ = (
        # We rely on filtered semantics in the repo (NULL never equals NULL),
        # so each (user, scope-target, position, level) tuple is unique without
        # cross-scope collisions.
        UniqueConstraint(
            "user_id", "project_id", "position", "level", name="uq_qa_sets_scope"
        ),
        UniqueConstraint(
            "user_id", "resume_id", "position", "level", name="uq_qa_sets_resume_scope"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="project"
    )  # project | resume
    position: Mapped[str] = mapped_column(String(64), nullable=False, default="swe")
    level: Mapped[str] = mapped_column(String(32), nullable=False)  # junior|mid|senior|tech_lead
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending|running|ready|failed
    total: Mapped[int] = mapped_column(default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)


class QAItem(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "qa_items"

    qa_set_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("qa_sets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    ideal_answer: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[Any] = mapped_column(JsonType, nullable=True)  # [{rel_path, start, end, snippet}]
    difficulty: Mapped[int] = mapped_column(default=3, nullable=False)  # 1-5
    tags: Mapped[Any] = mapped_column(JsonType, nullable=True)
    follow_up_axes: Mapped[Any] = mapped_column(JsonType, nullable=True)
    # Optional context populated for resume-scoped items: { "claim": str,
    # "claim_section": str, "source_project_id": str | None }. Project-scoped
    # items leave it NULL.
    meta: Mapped[Any] = mapped_column(JsonType, nullable=True)


class QAGenerationRun(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "qa_generation_runs"

    qa_set_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("qa_sets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    trigger: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[Any] = mapped_column(JsonType, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QAGenerationShard(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "qa_generation_shards"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("qa_generation_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    qa_set_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("qa_sets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    shard_key: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[Any] = mapped_column(JsonType, nullable=True)
