from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import EpisodicMemory, LongTermMemory


_UNSET = object()


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
        project_id: UUID | None = None,
        kind: str,
        content: str,
        weight: float = 1.0,
        pinned: bool = False,
        meta: dict | None = None,
        embedding_ref: str | None = None,
        source_session_id: UUID | None = None,
    ) -> LongTermMemory:
        row = LongTermMemory(
            user_id=user_id,
            project_id=project_id,
            kind=kind,
            content=content,
            weight=weight,
            pinned=pinned,
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
        project_id: UUID | None = None,
        pinned: bool | None = None,
        limit: int = 50,
    ) -> list[LongTermMemory]:
        q = select(LongTermMemory).where(LongTermMemory.user_id == user_id)
        if kind:
            q = q.where(LongTermMemory.kind == kind)
        if project_id is not None:
            q = q.where(LongTermMemory.project_id == project_id)
        if pinned is not None:
            q = q.where(LongTermMemory.pinned == pinned)
        q = q.order_by(
            LongTermMemory.pinned.desc(),
            LongTermMemory.weight.desc(),
            LongTermMemory.created_at.desc(),
        ).limit(limit)
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

    async def update_long_term(
        self,
        *,
        user_id: UUID,
        memory_id: UUID,
        pinned: bool | None = None,
        project_id: UUID | None | object = _UNSET,
    ) -> LongTermMemory | None:
        row = await self._s.get(LongTermMemory, memory_id)
        if row is None or row.user_id != user_id:
            return None
        if pinned is not None:
            row.pinned = pinned
        # Passing project_id=None intentionally clears the namespace.
        row.project_id = project_id if project_id is not _UNSET else row.project_id
        await self._s.commit()
        await self._s.refresh(row)
        return row
