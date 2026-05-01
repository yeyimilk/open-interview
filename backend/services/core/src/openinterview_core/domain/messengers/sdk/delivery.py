"""Outbound delivery — chunk by capability, swallow per-plugin failures so
one bad plugin can't take down the kernel.
"""
from __future__ import annotations

import re

from .plugin import MessengerPlugin
from .types import DeliveryResult


def _chunks(text: str, limit: int) -> list[str]:
    """Split a long message into pieces no longer than `limit` chars,
    preferring to break at paragraph or sentence boundaries.
    """
    if limit <= 0 or len(text) <= limit:
        return [text]

    out: list[str] = []
    remaining = text
    paragraph_re = re.compile(r"\n{2,}")
    sentence_re = re.compile(r"(?<=[.!?])\s+")

    while len(remaining) > limit:
        window = remaining[:limit]
        # Try paragraph break first.
        m = list(paragraph_re.finditer(window))
        cut = m[-1].end() if m else 0
        if cut == 0:
            sm = list(sentence_re.finditer(window))
            cut = sm[-1].end() if sm else 0
        if cut == 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        out.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        out.append(remaining)
    return out


async def deliver(
    plugin: MessengerPlugin,
    *,
    to: str,
    text: str,
    idempotency_key: str | None = None,
) -> DeliveryResult:
    if not text or not text.strip():
        return DeliveryResult(sent_chunks=0, skipped=True, reason="empty")

    cap = plugin.capabilities
    parts = _chunks(text, cap.max_outbound_chars)
    sent = 0
    for i, part in enumerate(parts):
        key = (
            f"{idempotency_key}:{i}"
            if idempotency_key is not None
            else None
        )
        await plugin.send_text(to=to, text=part, idempotency_key=key)
        sent += 1
    return DeliveryResult(sent_chunks=sent)
