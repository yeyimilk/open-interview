from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import User
from openinterview_schemas import (
    GenerateQARequest,
    GenerateQAResponse,
    QAEvidence,
    QAItemOut,
    QASetDetail,
    QASetOut,
)

from ...domain.qa import QAGenerationService
from ...infra.db import get_session_dep
from ...infra.db.qa_repository import SqlQARepository
from ..deps import get_current_user

router = APIRouter(tags=["qa"])


def _service(request: Request) -> QAGenerationService:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return QAGenerationService(
        sessionmaker=sm,
        gateway=request.app.state.gateway,
        vector_store=request.app.state.vector_store,
    )


async def _safe_run(svc: QAGenerationService, **kwargs) -> None:
    try:
        await svc.run(**kwargs)
    except Exception:
        pass


@router.post(
    "/projects/{project_id}/qa:generate",
    response_model=GenerateQAResponse,
)
async def generate_qa(
    project_id: UUID,
    body: GenerateQARequest,
    background: BackgroundTasks,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> GenerateQAResponse:
    repo = SqlQARepository(session)
    ids: list[UUID] = []
    for level in body.levels:
        qa_set = await repo.get_or_create_set(
            user_id=user.id,
            project_id=project_id,
            position=body.position,
            level=level,
        )
        ids.append(qa_set.id)
        await repo.set_status(qa_set_id=qa_set.id, status="pending", error=None)

    svc = _service(request)
    for level in body.levels:
        background.add_task(
            _safe_run,
            svc,
            user_id=user.id,
            project_id=project_id,
            position=body.position,
            level=level,
        )
    return GenerateQAResponse(qa_set_ids=ids)


@router.get("/projects/{project_id}/qa", response_model=list[QASetOut])
async def list_qa_sets(
    project_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[QASetOut]:
    items = await SqlQARepository(session).list_sets_for_project(
        user_id=user.id, project_id=project_id
    )
    return [
        QASetOut(
            id=i.id,
            project_id=i.project_id,
            position=i.position,
            level=i.level,
            status=i.status,
            total=i.total,
            error=i.error,
            created_at=i.created_at,
        )
        for i in items
    ]


@router.get("/qa-sets/{qa_set_id}", response_model=QASetDetail)
async def get_qa_set(
    qa_set_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> QASetDetail:
    repo = SqlQARepository(session)
    qa_set = await repo.get_set(user_id=user.id, qa_set_id=qa_set_id)
    if qa_set is None:
        raise HTTPException(status_code=404, detail="not found")
    items = await repo.list_items(user_id=user.id, qa_set_id=qa_set_id)
    return QASetDetail(
        id=qa_set.id,
        project_id=qa_set.project_id,
        position=qa_set.position,
        level=qa_set.level,
        status=qa_set.status,
        total=qa_set.total,
        error=qa_set.error,
        created_at=qa_set.created_at,
        items=[
            QAItemOut(
                id=i.id,
                category=i.category,
                level=i.level,
                question=i.question,
                ideal_answer=i.ideal_answer,
                evidence=[
                    QAEvidence(
                        rel_path=e.get("rel_path", ""),
                        start_line=e.get("start_line", 0),
                        end_line=e.get("end_line", 0),
                        snippet=e.get("snippet", ""),
                    )
                    for e in (i.evidence or [])
                ],
                difficulty=i.difficulty,
                tags=i.tags or [],
            )
            for i in items
        ],
    )


@router.post(
    "/qa-sets/{qa_set_id}:regenerate",
    response_model=QASetOut,
)
async def regenerate_qa_set(
    qa_set_id: UUID,
    background: BackgroundTasks,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> QASetOut:
    repo = SqlQARepository(session)
    qa_set = await repo.get_set(user_id=user.id, qa_set_id=qa_set_id)
    if qa_set is None:
        raise HTTPException(status_code=404, detail="not found")
    await repo.set_status(qa_set_id=qa_set.id, status="pending", error=None)
    svc = _service(request)
    background.add_task(
        _safe_run,
        svc,
        user_id=user.id,
        project_id=qa_set.project_id,
        position=qa_set.position,
        level=qa_set.level,
    )
    return QASetOut(
        id=qa_set.id,
        project_id=qa_set.project_id,
        position=qa_set.position,
        level=qa_set.level,
        status="pending",
        total=qa_set.total,
        error=None,
        created_at=qa_set.created_at,
    )
