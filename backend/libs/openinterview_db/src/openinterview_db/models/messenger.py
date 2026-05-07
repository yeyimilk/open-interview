from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ._mixins import TimestampMixin, UUIDPKMixin


class MessengerLink(UUIDPKMixin, TimestampMixin, Base):
    """A confirmed binding between (channel, external_id) and a user.

    Channel is the plugin id (e.g. "whatsapp"). External_id is whatever the
    plugin uses to identify a remote user (phone, openid, slack-user-id, …).
    """

    __tablename__ = "messenger_links"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_messenger_links_channel_external"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # How to apply the per-conversation filter rules (see MessengerFilter).
    #   "dms_only"  : DMs to the linked owner only (default; safe baseline)
    #   "allowlist" : forward only conversations matching any rule
    #   "denylist"  : forward everything except conversations matching a rule
    #   "all"       : forward everything (DMs and groups)
    filter_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="dms_only", default="dms_only"
    )


class MessengerFilter(UUIDPKMixin, TimestampMixin, Base):
    """Allow / deny rule for a MessengerLink.

    `kind` semantics:
      "phone": value is an E.164-style digit-only phone number; matches a
               1:1 chat where the JID is "<value>@s.whatsapp.net" or a group
               sender (key.participant) prefixed with that phone.
      "group": value is a WhatsApp group JID like "<n>-<n>@g.us".
    """

    __tablename__ = "messenger_filters"
    __table_args__ = (
        UniqueConstraint(
            "link_id", "kind", "value", name="uq_messenger_filters_link_kind_value"
        ),
    )

    link_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messenger_links.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # phone|group
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)


class MessengerPairToken(UUIDPKMixin, TimestampMixin, Base):
    """One-shot QR-pair token. User mints it from the web app; user's first
    DM to the bot via the deep-link redeems it and writes a MessengerLink.
    """

    __tablename__ = "messenger_pair_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    # SHA256 of the secret token; the secret itself is shown to the user once.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessengerActiveSession(UUIDPKMixin, TimestampMixin, Base):
    """The active mentor/interviewer session for a (user, channel, conversation)
    pair, so the kernel knows where to route plain messages.
    """

    __tablename__ = "messenger_active_sessions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "channel",
            "conversation_id",
            name="uq_messenger_active_user_channel_conversation",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(
        String(256), nullable=True, index=True
    )
    chat_session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False)  # mentor|interviewer


class MessengerInboundDedup(UUIDPKMixin, TimestampMixin, Base):
    """Idempotency record for inbound webhooks — (channel, message_id) pairs
    we have already processed. Plugins may not always provide message_id; in
    that case the SDK will fall back to (channel, sha256(payload)).
    """

    __tablename__ = "messenger_inbound_dedup"
    __table_args__ = (
        UniqueConstraint("channel", "message_id", name="uq_messenger_dedup_channel_msg"),
    )

    channel: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String(256), nullable=False)
