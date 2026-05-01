"""Plugin contract — the only thing the kernel and registry know about.

A messenger plugin must:
  * Provide a manifest describing its identity and capabilities.
  * Verify and parse inbound webhook requests into `InboundTurn`s.
  * Send outbound text (and optionally typing indicators).
  * Render its pair-link template so the web UI can build a QR.

This file is deliberately light on machinery so that adding WeChat,
Telegram, Slack, Lark, Discord, iMessage etc. is a folder drop-in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from fastapi import APIRouter, Request

from .types import InboundTurn


@dataclass(slots=True, frozen=True)
class MessengerCapabilities:
    """Per-plugin behavior flags. The kernel reads these instead of
    hard-coding `if channel == ...` branches.
    """

    streaming: bool = False
    max_outbound_chars: int = 4000
    inbound_voice: bool = False
    inbound_image: bool = False
    rich_buttons: bool = False
    ack_window_s: int = 20
    pair_link_scheme: str = "url"  # "url" | "qr-only" | "custom"
    supports_typing: bool = False


@dataclass(slots=True)
class MessengerIdentity:
    id: str
    name: str
    description: str = ""
    config_schema: dict = field(default_factory=dict)


class MessengerPlugin(Protocol):
    """Stable contract every messenger plugin implements."""

    identity: MessengerIdentity
    capabilities: MessengerCapabilities

    # --- inbound ------------------------------------------------------------

    def webhook_router(self) -> APIRouter:
        """Return a FastAPI router rooted at "/" so it can be mounted under
        `/webhooks/{plugin_id}`. The router's handlers should call back into
        `verify_signature` + `parse_inbound` and then hand turns to the
        kernel that was supplied at registration time.
        """
        ...

    async def verify_signature(self, request: Request, body: bytes) -> bool: ...

    async def parse_inbound(
        self, request: Request, body: bytes
    ) -> list[InboundTurn]: ...

    # --- outbound -----------------------------------------------------------

    async def send_text(
        self,
        to: str,
        text: str,
        *,
        idempotency_key: str | None = None,
    ) -> None: ...

    async def send_typing(self, to: str) -> None: ...

    # --- pairing ------------------------------------------------------------

    def pair_link_template(self) -> str:
        """Return a template string with `{token}` placeholder. The web UI
        substitutes the QR-pair token to build a deep link / QR code.
        """
        ...

    # --- lifecycle ----------------------------------------------------------

    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...
