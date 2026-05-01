from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from openinterview_db import UserApiKey

from ...domain.keys.interface import KeyResolver, ResolvedKey


class SqlKeyResolver(KeyResolver):
    """BYO from DB; falls back to admin-shared key from env."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        decrypt: callable,  # type: ignore[type-arg]  -- (bytes) -> str
        shared_keys: dict[str, str],
    ) -> None:
        self._sessionmaker = sessionmaker
        self._decrypt = decrypt
        self._shared_keys = {k.lower(): v for k, v in shared_keys.items() if v}

    async def resolve(self, *, user_id: UUID, provider: str) -> ResolvedKey | None:
        async with self._sessionmaker() as s:
            row = await self._get_byo(s, user_id, provider)
        if row is not None:
            return ResolvedKey(mode="byo", api_key=self._decrypt(row.encrypted_key))
        shared = self._shared_keys.get(provider.lower())
        if shared:
            return ResolvedKey(mode="shared", api_key=shared)
        return None

    @staticmethod
    async def _get_byo(s: AsyncSession, user_id: UUID, provider: str) -> UserApiKey | None:
        q = (
            select(UserApiKey)
            .where(UserApiKey.user_id == user_id, UserApiKey.provider == provider)
            .order_by(UserApiKey.created_at.desc())
            .limit(1)
        )
        return (await s.execute(q)).scalar_one_or_none()
