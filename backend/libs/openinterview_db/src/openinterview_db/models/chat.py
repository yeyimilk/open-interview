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


class ChatSession(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)  # mentor|interviewer
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target: Mapped[Any] = mapped_column(JsonType, nullable=True)  # {position, level, n_questions, ...}
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")  # active|ended
    turn_count: Mapped[int] = mapped_column(default=0, nullable=False)


class ChatMessage(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user|assistant|system|tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[Any] = mapped_column(JsonType, nullable=True)


class InterviewEvaluation(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "interview_evaluations"

    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    overall_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    scores: Mapped[Any] = mapped_column(JsonType, nullable=True)  # {category: 1-5}
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths: Mapped[Any] = mapped_column(JsonType, nullable=True)
    weaknesses: Mapped[Any] = mapped_column(JsonType, nullable=True)
    suggested_practice: Mapped[Any] = mapped_column(JsonType, nullable=True)
