from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import User
from openinterview_schemas import LongTermMemoryOut, LongTermMemoryUpdate

from ...infra.db import get_session_dep
from ...infra.db.memory_repository import _UNSET, SqlMemoryRepository
from ..deps import get_current_user

router = APIRouter(prefix="/memory", tags=["memory"])


def _out(row) -> LongTermMemoryOut:
    return LongTermMemoryOut(
        id=row.id,
        user_id=row.user_id,
        project_id=row.project_id,
        kind=row.kind,
        content=row.content,
        weight=row.weight,
        pinned=row.pinned,
        meta=row.meta,
        source_session_id=row.source_session_id,
        created_at=row.created_at,
    )


@router.get("/long-term", response_model=list[LongTermMemoryOut])
async def list_long_term_memory(
    kind: str | None = None,
    project_id: UUID | None = None,
    pinned: bool | None = None,
    limit: int = 100,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[LongTermMemoryOut]:
    rows = await SqlMemoryRepository(session).list_long_term(
        user_id=user.id,
        kind=kind,
        project_id=project_id,
        pinned=pinned,
        limit=max(1, min(limit, 200)),
    )
    return [_out(row) for row in rows]


@router.patch("/long-term/{memory_id}", response_model=LongTermMemoryOut)
async def update_long_term_memory(
    memory_id: UUID,
    body: LongTermMemoryUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> LongTermMemoryOut:
    row = await SqlMemoryRepository(session).update_long_term(
        user_id=user.id,
        memory_id=memory_id,
        pinned=body.pinned,
        project_id=body.project_id if "project_id" in body.model_fields_set else _UNSET,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _out(row)
