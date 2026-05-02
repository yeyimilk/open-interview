from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import UserModelPreference


class SqlUserModelPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_for_user(self, *, user_id: UUID) -> list[UserModelPreference]:
        rows = (
            await self._s.execute(
                select(UserModelPreference).where(
                    UserModelPreference.user_id == user_id
                )
            )
        ).scalars().all()
        return list(rows)

    async def get(
        self, *, user_id: UUID, role: str
    ) -> UserModelPreference | None:
        return (
            await self._s.execute(
                select(UserModelPreference).where(
                    UserModelPreference.user_id == user_id,
                    UserModelPreference.role == role,
                )
            )
        ).scalars().first()

    async def upsert(
        self,
        *,
        user_id: UUID,
        role: str,
        provider: str,
        endpoint: str,
        model_id: str,
    ) -> UserModelPreference:
        existing = await self.get(user_id=user_id, role=role)
        if existing is None:
            row = UserModelPreference(
                user_id=user_id,
                role=role,
                provider=provider,
                endpoint=endpoint,
                model_id=model_id,
            )
            self._s.add(row)
        else:
            existing.provider = provider
            existing.endpoint = endpoint
            existing.model_id = model_id
            row = existing
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def delete(self, *, user_id: UUID, role: str) -> bool:
        result = await self._s.execute(
            delete(UserModelPreference).where(
                UserModelPreference.user_id == user_id,
                UserModelPreference.role == role,
            )
        )
        await self._s.commit()
        return (result.rowcount or 0) > 0
