from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import UserApiKey


class SqlApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(
        self, *, user_id: UUID, provider: str, label: str, encrypted_key: bytes
    ) -> UserApiKey:
        row = UserApiKey(
            user_id=user_id, provider=provider, label=label, encrypted_key=encrypted_key
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def list(self, *, user_id: UUID) -> list[UserApiKey]:
        q = (
            select(UserApiKey)
            .where(UserApiKey.user_id == user_id)
            .order_by(UserApiKey.created_at.desc())
        )
        return list((await self._s.execute(q)).scalars())

    async def delete(self, *, user_id: UUID, key_id: UUID) -> bool:
        q = delete(UserApiKey).where(
            UserApiKey.id == key_id, UserApiKey.user_id == user_id
        )
        result = await self._s.execute(q)
        await self._s.commit()
        return (result.rowcount or 0) > 0
