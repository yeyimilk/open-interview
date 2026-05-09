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

JsonType = JSON().with_variant(JSONB(), "postgresql")


class Resume(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "resumes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="text/plain")
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed: Mapped[Any] = mapped_column(JsonType, nullable=True)  # sections, claims, skills


class ClaimMapping(UUIDPKMixin, TimestampMixin, Base):
    """Maps a resume claim to project facts that ground it."""
    __tablename__ = "claim_mappings"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    resume_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    grounding: Mapped[Any] = mapped_column(JsonType, nullable=True)  # list of {file, lines, evidence}
    confidence: Mapped[int] = mapped_column(default=0, nullable=False)  # 0..100
