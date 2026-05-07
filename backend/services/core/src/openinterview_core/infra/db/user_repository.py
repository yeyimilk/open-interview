from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import User


class SqlUserRepository:
    """Concrete UserRepository backed by SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self._s.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._s.get(User, user_id)

    async def count_users(self) -> int:
        result = await self._s.execute(select(func.count()).select_from(User))
        return int(result.scalar_one())

    async def count_admins(self) -> int:
        result = await self._s.execute(
            select(func.count()).select_from(User).where(User.is_admin.is_(True))
        )
        return int(result.scalar_one())

    async def list_users(self) -> list[User]:
        result = await self._s.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())

    async def create(
        self, *, email: str, password_hash: str, display_name: str, is_admin: bool = False
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
            is_admin=is_admin,
        )
        self._s.add(user)
        await self._s.commit()
        await self._s.refresh(user)
        return user

    async def update_user(
        self,
        user_id: UUID,
        *,
        tier: str | None = None,
        is_admin: bool | None = None,
    ) -> User | None:
        user = await self.get_by_id(user_id)
        if user is None:
            return None
        if tier is not None:
            user.tier = tier
        if is_admin is not None:
            user.is_admin = is_admin
        await self._s.commit()
        await self._s.refresh(user)
        return user
