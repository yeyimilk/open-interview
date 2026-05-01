"""Channel-agnostic types shared between the kernel and every plugin."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class Attachment:
    """Normalized inbound attachment.

    `bytes_url` is an opaque URL the plugin gives the kernel to fetch the
    binary later (signed URL, file:// path, etc.). The SDK never assumes
    the URL is publicly reachable.
    """

    kind: str  # "audio" | "image" | "file" | "sticker" | "video"
    mime: str
    bytes_url: str | None = None
    inline_bytes: bytes | None = None
    filename: str | None = None
    duration_s: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InboundTurn:
    """One message arriving from a remote user.

    Plugins build this in `parse_inbound`; the kernel never inspects raw.

    Two ids are tracked because messengers like WhatsApp distinguish the
    *sender* of a message from the *chat* it lives in:
      - `external_user_id` is always the sender (e.g. their WA-jid)
      - `chat_id` is the conversation (same as sender for DMs; the group
        JID for group messages). Plugins that don't have groups can
        leave it equal to external_user_id.
      - `is_group` mirrors `chat_id != external_user_id` but is kept
        explicit so the kernel doesn't have to guess.
    """

    channel: str
    external_user_id: str
    text: str
    attachments: list[Attachment] = field(default_factory=list)
    message_id: str | None = None  # for idempotency, when the platform exposes one
    sender_display_name: str | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    chat_id: str | None = None
    is_group: bool = False
    # The `external_id` of the MessengerLink that owns this conversation.
    # For DMs this equals `external_user_id`; for groups it's the owner's
    # JID (the user who paired the bot), so the kernel can resolve a link
    # even when the sender is some other group member.
    link_external_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutboundReply:
    """Logical reply produced by the kernel; the SDK delivery layer turns it
    into one or more concrete sends, respecting plugin capabilities.
    """

    text: str
    quick_replies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeliveryResult:
    sent_chunks: int
    skipped: bool = False
    reason: str | None = None
