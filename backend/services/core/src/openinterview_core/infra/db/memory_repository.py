from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import EpisodicMemory, LongTermMemory


class SqlMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ---------- Episodic ----------

    async def add_episodic(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        summary: str,
        entities: dict | None = None,
        embedding_ref: str | None = None,
    ) -> EpisodicMemory:
        row = EpisodicMemory(
            user_id=user_id,
            session_id=session_id,
            summary=summary,
            entities=entities,
            embedding_ref=embedding_ref,
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def list_episodic(
        self, *, user_id: UUID, limit: int = 10
    ) -> list[EpisodicMemory]:
        q = (
            select(EpisodicMemory)
            .where(EpisodicMemory.user_id == user_id)
            .order_by(EpisodicMemory.created_at.desc())
            .limit(limit)
        )
        return list((await self._s.execute(q)).scalars())

    # ---------- Long-term ----------

    async def add_long_term(
        self,
        *,
        user_id: UUID,
        kind: str,
        content: str,
        weight: float = 1.0,
        meta: dict | None = None,
        embedding_ref: str | None = None,
        source_session_id: UUID | None = None,
    ) -> LongTermMemory:
        row = LongTermMemory(
            user_id=user_id,
            kind=kind,
            content=content,
            weight=weight,
            meta=meta,
            embedding_ref=embedding_ref,
            source_session_id=source_session_id,
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def list_long_term(
        self,
        *,
        user_id: UUID,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[LongTermMemory]:
        q = select(LongTermMemory).where(LongTermMemory.user_id == user_id)
        if kind:
            q = q.where(LongTermMemory.kind == kind)
        q = q.order_by(LongTermMemory.weight.desc(), LongTermMemory.created_at.desc()).limit(limit)
        return list((await self._s.execute(q)).scalars())

    async def get_by_ids(
        self, *, user_id: UUID, ids: list[UUID]
    ) -> list[LongTermMemory]:
        if not ids:
            return []
        q = select(LongTermMemory).where(
            LongTermMemory.user_id == user_id, LongTermMemory.id.in_(ids)
        )
        return list((await self._s.execute(q)).scalars())
