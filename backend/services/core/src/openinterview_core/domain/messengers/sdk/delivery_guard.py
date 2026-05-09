"""Outbound delivery safety net.

Three knobs, applied in order, per recipient:

  1. Repeat-suppressor: if the same exact text was sent within the last N
     messages to this recipient, drop it. Catches agent-loop bugs where a
     model echoes its own output and would otherwise send the same wall of
     text 5 times in a row.

  2. Token-bucket rate limiter: cap the *raw send rate* (messages per
     second per recipient). This is a safety net, not a UX choice — it
     stops a runaway loop from getting our number banned by WhatsApp.

  3. Length splitter + paced sender: long replies are chunked at sentence
     boundaries (already handled by `delivery.deliver`), and we sleep a
     short pause between chunks so the platform doesn't reorder them.

All state is in-memory and per-process. After a restart we re-learn from
scratch — that's fine; these are just guard-rails.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

from openinterview_logging import get_logger

from .delivery import _chunks
from .plugin import MessengerPlugin
from .types import DeliveryResult

log = get_logger(__name__)


@dataclass(slots=True)
class _Bucket:
    # Token-bucket state.
    tokens: float
    last_refill: float
    # Recent message hashes for dedup, oldest-first.
    recent: deque = field(default_factory=lambda: deque(maxlen=3))


@dataclass(frozen=True, slots=True)
class DeliveryProfile:
    rate_per_second: float
    burst: int
    recent_window: int
    chunk_pause_s: float
    max_chars_per_chunk: int | None


DEFAULT_DELIVERY_PROFILES: dict[str, DeliveryProfile] = {
    "free": DeliveryProfile(
        rate_per_second=1.0,
        burst=8,
        recent_window=3,
        chunk_pause_s=0.8,
        max_chars_per_chunk=1600,
    ),
    "pro": DeliveryProfile(
        rate_per_second=2.0,
        burst=12,
        recent_window=3,
        chunk_pause_s=0.35,
        max_chars_per_chunk=2400,
    ),
    "team": DeliveryProfile(
        rate_per_second=4.0,
        burst=20,
        recent_window=4,
        chunk_pause_s=0.2,
        max_chars_per_chunk=3200,
    ),
}


class DeliveryGuard:
    """Stateful per-recipient guard. One instance per plugin runtime."""

    def __init__(
        self,
        *,
        rate_per_second: float = 1.0,
        burst: int = 5,
        recent_window: int = 3,
        chunk_pause_s: float = 0.4,
        max_chars_per_chunk: int | None = None,
        profiles: dict[str, DeliveryProfile] | None = None,
    ) -> None:
        self._default_profile = DeliveryProfile(
            rate_per_second=rate_per_second,
            burst=burst,
            recent_window=recent_window,
            chunk_pause_s=chunk_pause_s,
            max_chars_per_chunk=max_chars_per_chunk,
        )
        self._profiles = profiles or DEFAULT_DELIVERY_PROFILES
        self._buckets: dict[str, _Bucket] = {}

    def _profile_for(self, tier: str | None) -> DeliveryProfile:
        if tier is None:
            return self._default_profile
        normalized = tier.strip().lower()
        if normalized in {"paid", "plus"}:
            normalized = "pro"
        if normalized in {"enterprise", "business"}:
            normalized = "team"
        return self._profiles.get(normalized, self._default_profile)

    def _bucket(self, key: str, profile: DeliveryProfile) -> _Bucket:
        b = self._buckets.get(key)
        if b is None:
            b = _Bucket(
                tokens=float(profile.burst),
                last_refill=time.monotonic(),
                recent=deque(maxlen=profile.recent_window),
            )
            self._buckets[key] = b
        return b

    def _take_token(self, b: _Bucket, profile: DeliveryProfile) -> bool:
        now = time.monotonic()
        elapsed = max(0.0, now - b.last_refill)
        b.tokens = min(profile.burst, b.tokens + elapsed * profile.rate_per_second)
        b.last_refill = now
        if b.tokens >= 1.0:
            b.tokens -= 1.0
            return True
        return False

    def _is_repeat(self, b: _Bucket, text: str) -> bool:
        # Compare normalized form so trivial whitespace changes don't
        # defeat the dedup, but text differences (even one word) do.
        norm = " ".join(text.split())
        return norm in b.recent

    def _remember(self, b: _Bucket, text: str) -> None:
        b.recent.append(" ".join(text.split()))

    async def deliver(
        self,
        plugin: MessengerPlugin,
        *,
        to: str,
        text: str,
        idempotency_key: str | None = None,
        tier: str | None = None,
    ) -> DeliveryResult:
        if not text or not text.strip():
            return DeliveryResult(sent_chunks=0, skipped=True, reason="empty")

        profile = self._profile_for(tier)
        b = self._bucket(to, profile)

        if self._is_repeat(b, text):
            log.info(
                "delivery_guard_repeat_drop",
                to_tail=to[-6:] if to else "",
                len=len(text),
            )
            return DeliveryResult(
                sent_chunks=0, skipped=True, reason="repeat"
            )

        if not self._take_token(b, profile):
            log.warning(
                "delivery_guard_rate_limited",
                to_tail=to[-6:] if to else "",
                tier=tier or "free",
                rate_per_second=profile.rate_per_second,
                burst=profile.burst,
            )
            return DeliveryResult(
                sent_chunks=0, skipped=True, reason="rate_limited"
            )

        # Length-split: prefer the caller's plugin capability, but cap further
        # if the guard was configured with a smaller limit.
        cap_limit = plugin.capabilities.max_outbound_chars
        limit = (
            min(cap_limit, profile.max_chars_per_chunk)
            if (profile.max_chars_per_chunk is not None)
            else cap_limit
        )
        parts = _chunks(text, limit)

        # Annotate multi-part messages so users don't think they got
        # truncated. e.g. "(1/3) Lorem ipsum…"
        if len(parts) > 1:
            parts = [f"({i + 1}/{len(parts)}) {p}" for i, p in enumerate(parts)]

        sent = 0
        for i, part in enumerate(parts):
            key = (
                f"{idempotency_key}:{i}" if idempotency_key is not None else None
            )
            await plugin.send_text(to=to, text=part, idempotency_key=key)
            sent += 1
            if i < len(parts) - 1 and profile.chunk_pause_s > 0:
                await asyncio.sleep(profile.chunk_pause_s)

        # Remember the *original* text (pre-chunk, pre-numbering) so a
        # follow-up call with the same content is correctly flagged as a
        # repeat regardless of chunking.
        self._remember(b, text)
        return DeliveryResult(sent_chunks=sent)
