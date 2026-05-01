"""Mint and redeem one-shot QR-pair tokens.

A token is a 32-byte URL-safe random string shown to the web user once
(rendered as a QR via the plugin's `pair_link_template`). Only the SHA-256
hash is persisted, so leaking the DB doesn't leak active tokens.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import MessengerPairToken

DEFAULT_TTL = timedelta(minutes=10)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PairTokenError(Exception):
    pass


class PairTokenStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def mint(
        self, *, user_id: UUID, channel: str, ttl: timedelta = DEFAULT_TTL
    ) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(24)
        expires_at = datetime.now(timezone.utc) + ttl
        async with self._sm() as s:
            s.add(
                MessengerPairToken(
                    user_id=user_id,
                    channel=channel,
                    token_hash=_hash(token),
                    expires_at=expires_at,
                )
            )
            await s.commit()
        return token, expires_at

    async def redeem(self, *, channel: str, token: str) -> UUID:
        """Mark the token redeemed and return the owning user_id."""
        h = _hash(token)
        now = datetime.now(timezone.utc)
        async with self._sm() as s:
            row = (
                await s.execute(
                    select(MessengerPairToken).where(
                        MessengerPairToken.token_hash == h,
                        MessengerPairToken.channel == channel,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise PairTokenError("token not found")
            # Compare as naive UTC if DB returned naive (sqlite path).
            exp = row.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                raise PairTokenError("token expired")
            if row.redeemed_at is not None:
                raise PairTokenError("token already redeemed")
            row.redeemed_at = now
            user_id = row.user_id
            await s.commit()
        return user_id
