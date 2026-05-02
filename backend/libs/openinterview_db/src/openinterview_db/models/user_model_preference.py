from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ._mixins import TimestampMixin, UUIDPKMixin


class UserModelPreference(UUIDPKMixin, TimestampMixin, Base):
    """Per-user override for which model handles a given role.

    A row means: for ``role`` (one of chat | embedding | transcription |
    voice-analysis), use this exact ``(provider, endpoint, model_id)`` triple
    instead of the catalog default. Absence of a row → catalog default.
    """

    __tablename__ = "user_model_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_user_model_pref_user_role"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(String(256), nullable=False)
