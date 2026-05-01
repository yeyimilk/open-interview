from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import GatewayUsageLog

from ...domain.usage.interface import UsageEvent, UsageRepository


class SqlUsageRepository(UsageRepository):
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def record(self, event: UsageEvent) -> None:
        row = GatewayUsageLog(
            user_id=event.user_id,
            mode=event.mode,
            logical_model=event.logical_model,
            provider=event.provider,
            endpoint=event.endpoint,
            prompt_tokens=event.usage.prompt_tokens,
            completion_tokens=event.usage.completion_tokens,
            total_tokens=event.usage.total_tokens,
            latency_ms=event.latency_ms,
            status=event.status,
            error=event.error,
        )
        async with self._sm() as s:
            s.add(row)
            await s.commit()
