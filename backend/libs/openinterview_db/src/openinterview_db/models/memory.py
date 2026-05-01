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


class EpisodicMemory(UUIDPKMixin, TimestampMixin, Base):
    """Per-session distilled summary."""
    __tablename__ = "episodic_memories"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    entities: Mapped[Any] = mapped_column(JsonType, nullable=True)  # {projects:[], topics:[], questions:[]}
    embedding_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)


class LongTermMemory(UUIDPKMixin, TimestampMixin, Base):
    """User-level durable memory: strengths, gaps, preferences, facts."""
    __tablename__ = "long_term_memories"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # strength|gap|preference|fact
    content: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(default=1.0, nullable=False)
    meta: Mapped[Any] = mapped_column(JsonType, nullable=True)
    embedding_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
