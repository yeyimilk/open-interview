"""Key resolution: BYO vs shared. Returns the credential to use plus the mode."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID


Mode = Literal["byo", "shared"]


@dataclass(frozen=True)
class ResolvedKey:
    mode: Mode
    api_key: str


class KeyResolver(Protocol):
    async def resolve(self, *, user_id: UUID, provider: str) -> ResolvedKey | None: ...
