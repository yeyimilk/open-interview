from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import User
from openinterview_schemas import (
    QAGenerationRunOut,
    QAEvidence,
    QAItemOut,
    QASetDetail,
    QASetOut,
    QASetReviewRequest,
)

from ...domain.qa import QAGenerationService
from ...infra.db import get_session_dep
from ...infra.db.qa_repository import SqlQARepository
from ...infra.jobs import enqueue_arq_job
from ..deps import require_admin

router = APIRouter(prefix="/admin/qa-sets", tags=["admin-qa"])


def _run_out(row) -> QAGenerationRunOut | None:
    if row is None:
        return None
    return QAGenerationRunOut(
        id=row.id,
        status=row.status,
        attempt=row.attempt,
        trigger=row.trigger,
        error=row.error,
        meta=row.meta,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


async def _set_out(repo: SqlQARepository, row) -> QASetOut:
    latest = await repo.latest_generation_run(qa_set_id=row.id)
    return QASetOut(
        id=row.id,
        project_id=row.project_id,
        resume_id=row.resume_id,
        scope=row.scope,
        position=row.position,
        level=row.level,
        status=row.status,
        total=row.total,
        error=row.error,
        review_status=row.review_status,
        review_notes=row.review_notes,
        reviewed_at=row.reviewed_at,
        generation_run=_run_out(latest),
        created_at=row.created_at,
    )


def _service(request: Request) -> QAGenerationService:
    sm: async_sessionmaker = request.app.state.db.sessionmaker
    return QAGenerationService(
        sessionmaker=sm,
        gateway=request.app.state.gateway,
        vector_store=request.app.state.vector_store,
        retrieval_service=request.app.state.retrieval_service,
    )


async def _safe_run(svc: QAGenerationService, kwargs: dict) -> None:
    try:
        if kwargs["scope"] == "resume":
            await svc.run_for_resume(**{k: v for k, v in kwargs.items() if k != "scope"})
        else:
            await svc.run(**{k: v for k, v in kwargs.items() if k != "scope"})
    except Exception:
        pass


@router.get("", response_model=list[QASetOut])
async def list_qa_sets(
    status: str | None = None,
    review_status: str | None = None,
    limit: int = 100,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> list[QASetOut]:
    repo = SqlQARepository(session)
    rows = await repo.list_sets(status=status, review_status=review_status, limit=limit)
    return [await _set_out(repo, row) for row in rows]


@router.get("/{qa_set_id}", response_model=QASetDetail)
async def get_qa_set(
    qa_set_id: UUID,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> QASetDetail:
    repo = SqlQARepository(session)
    row = await repo.get_set_any(qa_set_id=qa_set_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    items = await repo.list_items(user_id=row.user_id, qa_set_id=qa_set_id)
    latest = await repo.latest_generation_run(qa_set_id=qa_set_id)
    return QASetDetail(
        id=row.id,
        project_id=row.project_id,
        resume_id=row.resume_id,
        scope=row.scope,
        position=row.position,
        level=row.level,
        status=row.status,
        total=row.total,
        error=row.error,
        review_status=row.review_status,
        review_notes=row.review_notes,
        reviewed_at=row.reviewed_at,
        generation_run=_run_out(latest),
        created_at=row.created_at,
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
                follow_up_axes=i.follow_up_axes or [],
            )
            for i in items
        ],
    )


@router.patch("/{qa_set_id}/review", response_model=QASetOut)
async def review_qa_set(
    qa_set_id: UUID,
    body: QASetReviewRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> QASetOut:
    repo = SqlQARepository(session)
    row = await repo.get_set_any(qa_set_id=qa_set_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    updated = await repo.set_review(
        qa_set_id=qa_set_id,
        reviewer_user_id=admin.id,
        review_status=body.review_status,
        review_notes=body.review_notes,
    )
    return await _set_out(repo, updated)


@router.post("/{qa_set_id}:regenerate", response_model=QASetOut)
async def regenerate_qa_set(
    qa_set_id: UUID,
    background: BackgroundTasks,
    request: Request,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> QASetOut:
    repo = SqlQARepository(session)
    row = await repo.get_set_any(qa_set_id=qa_set_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    await repo.set_status(qa_set_id=qa_set_id, status="pending", error=None)
    settings = request.app.state.settings
    svc = _service(request)
    if row.scope == "resume":
        if row.resume_id is None:
            raise HTTPException(status_code=400, detail="qa set missing resume_id")
        args = (str(row.user_id), str(row.resume_id), row.position, row.level)
        queued = await enqueue_arq_job(settings.redis_url, "generate_resume_qa", *args)
        if not queued:
            background.add_task(
                _safe_run,
                svc,
                {
                    "scope": "resume",
                    "user_id": row.user_id,
                    "resume_id": row.resume_id,
                    "position": row.position,
                    "level": row.level,
                },
            )
    else:
        if row.project_id is None:
            raise HTTPException(status_code=400, detail="qa set missing project_id")
        args = (str(row.user_id), str(row.project_id), row.position, row.level)
        queued = await enqueue_arq_job(settings.redis_url, "generate_project_qa", *args)
        if not queued:
            background.add_task(
                _safe_run,
                svc,
                {
                    "scope": "project",
                    "user_id": row.user_id,
                    "project_id": row.project_id,
                    "position": row.position,
                    "level": row.level,
                },
            )
    row.status = "pending"
    row.error = None
    return await _set_out(repo, row)
