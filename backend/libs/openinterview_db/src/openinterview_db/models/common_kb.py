from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from ..base import Base
from ._mixins import TimestampMixin, UUIDPKMixin

JsonType = JSON().with_variant(JSONB(), "postgresql")


class CommonKBSpace(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "common_kb_spaces"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CommonKBSource(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "common_kb_sources"

    space_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("common_kb_spaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False, default="upload")
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str | None] = mapped_column(String(160), nullable=True)
    allowed_use: Mapped[Any] = mapped_column(JsonType, nullable=True)
    refresh_status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CommonKBDocument(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "common_kb_documents"

    space_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("common_kb_spaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("common_kb_sources.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(240), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    blob_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[Any] = mapped_column(JsonType, nullable=True)


class CommonKBItem(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "common_kb_items"

    space_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("common_kb_spaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("common_kb_sources.id", ondelete="SET NULL"), index=True, nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("common_kb_documents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    item_type: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_outline: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    role_family: Mapped[str | None] = mapped_column(String(80), nullable=True)
    level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    language: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    provenance: Mapped[Any] = mapped_column(JsonType, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CommonKBTag(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "common_kb_tags"
    __table_args__ = (
        UniqueConstraint("namespace", "normalized", name="uq_common_kb_tags_namespace_normalized"),
    )

    namespace: Mapped[str] = mapped_column(String(48), nullable=False, default="topic")
    value: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized: Mapped[str] = mapped_column(String(160), nullable=False, index=True)


class CommonKBItemTag(Base):
    __tablename__ = "common_kb_item_tags"
    __table_args__ = (
        UniqueConstraint("item_id", "tag_id", name="uq_common_kb_item_tags_item_tag"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("common_kb_items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("common_kb_tags.id", ondelete="CASCADE"), primary_key=True
    )


class CompanyInterviewProfile(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "company_interview_profiles"

    company_key: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    company: Mapped[str] = mapped_column(String(160), nullable=False)
    role_family: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category_weights: Mapped[Any] = mapped_column(JsonType, nullable=True)
    language_preferences: Mapped[Any] = mapped_column(JsonType, nullable=True)
    round_patterns: Mapped[Any] = mapped_column(JsonType, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.4)
    source_refs: Mapped[Any] = mapped_column(JsonType, nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UserInterviewPreference(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "user_interview_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, index=True, nullable=False)
    target_company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    category_weights: Mapped[Any] = mapped_column(JsonType, nullable=True)
    languages: Mapped[Any] = mapped_column(JsonType, nullable=True)
    interview_style: Mapped[str | None] = mapped_column(String(64), nullable=True)
    include_company_style: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
