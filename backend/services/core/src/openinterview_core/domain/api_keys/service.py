"""API key management. The plaintext key is encrypted on its way in;
only the encrypted blob is stored. Plaintext is never returned."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from openinterview_db import UserApiKey


class ApiKeyRepository(Protocol):
    async def add(
        self, *, user_id: UUID, provider: str, label: str, encrypted_key: bytes
    ) -> UserApiKey: ...
    async def list(self, *, user_id: UUID) -> list[UserApiKey]: ...
    async def delete(self, *, user_id: UUID, key_id: UUID) -> bool: ...


@dataclass(frozen=True)
class ApiKeyOut:
    id: UUID
    provider: str
    label: str
    created_at: datetime


class ApiKeyService:
    def __init__(self, repo: ApiKeyRepository, encrypt: callable) -> None:  # type: ignore[type-arg]
        self._repo = repo
        self._encrypt = encrypt

    async def add(
        self, *, user_id: UUID, provider: str, label: str, plaintext: str
    ) -> ApiKeyOut:
        if not plaintext.strip():
            raise ValueError("api key is empty")
        encrypted = self._encrypt(plaintext)
        row = await self._repo.add(
            user_id=user_id,
            provider=provider.strip().lower(),
            label=label.strip(),
            encrypted_key=encrypted,
        )
        return _to_out(row)

    async def list(self, *, user_id: UUID) -> list[ApiKeyOut]:
        rows = await self._repo.list(user_id=user_id)
        return [_to_out(r) for r in rows]

    async def delete(self, *, user_id: UUID, key_id: UUID) -> bool:
        return await self._repo.delete(user_id=user_id, key_id=key_id)


def _to_out(row: UserApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=row.id, provider=row.provider, label=row.label, created_at=row.created_at
    )
