"""Repository protocol for user persistence. The domain depends on this, not on SQL."""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from openinterview_db import User


class UserRepository(Protocol):
    async def get_by_email(self, email: str) -> User | None: ...
    async def get_by_id(self, user_id: UUID) -> User | None: ...
    async def create(
        self, *, email: str, password_hash: str, display_name: str
    ) -> User: ...
