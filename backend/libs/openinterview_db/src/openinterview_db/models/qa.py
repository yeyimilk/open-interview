from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
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
    # Optional context populated for resume-scoped items: { "claim": str,
    # "claim_section": str, "source_project_id": str | None }. Project-scoped
    # items leave it NULL.
    meta: Mapped[Any] = mapped_column(JsonType, nullable=True)
