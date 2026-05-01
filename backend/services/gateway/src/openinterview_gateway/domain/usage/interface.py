from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from openinterview_schemas import TokenUsage


@dataclass(frozen=True)
class UsageEvent:
    user_id: UUID
    mode: str  # byo | shared
    logical_model: str
    provider: str
    endpoint: str
    usage: TokenUsage
    latency_ms: int
    status: int
    error: str | None = None


class UsageRepository(Protocol):
    async def record(self, event: UsageEvent) -> None: ...
