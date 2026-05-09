from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import User
from openinterview_logging import get_logger
from openinterview_schemas import (
    GenerateQARequest,
    GenerateQAResponse,
    QAGenerationRunOut,
    QAEvidence,
    QAItemOut,
    QASetDetail,
    QASetOut,
)

from ...domain.qa import QAGenerationService
from ...infra.db import get_session_dep
from ...infra.db.qa_repository import SqlQARepository
from ...infra.jobs import enqueue_arq_job
from ..deps import get_current_user

router = APIRouter(tags=["qa"])
log = get_logger(__name__)


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
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return QAGenerationService(
        sessionmaker=sm,
        gateway=request.app.state.gateway,
        vector_store=request.app.state.vector_store,
        retrieval_service=request.app.state.retrieval_service,
    )


async def _safe_run(svc: QAGenerationService, **kwargs) -> None:
    try:
        await svc.run(**kwargs)
    except Exception:
        pass


async def _safe_run_for_resume(svc: QAGenerationService, **kwargs) -> None:
    try:
        await svc.run_for_resume(**kwargs)
    except Exception:
        pass


async def _enqueue_project_qa_or_fallback(
    *,
    request: Request,
    background: BackgroundTasks,
    svc: QAGenerationService,
    qa_set_id: UUID,
    user_id: UUID,
    project_id: UUID,
    position: str,
    level: str,
) -> None:
    settings = request.app.state.settings
    queued = await enqueue_arq_job(
        settings.redis_url,
        "generate_project_qa",
        str(user_id),
        str(project_id),
        position,
        level,
    )
    log.info(
        "qa_generation_enqueued",
        queued=queued,
        scope="project",
        user_id=str(user_id),
        project_id=str(project_id),
        position=position,
        level=level,
    )
    if not queued:
        if getattr(settings, "qa_generation_enqueue_required", False):
            async with request.app.state.db.sessionmaker() as s:
                await SqlQARepository(s).set_status(
                    qa_set_id=qa_set_id,
                    status="failed",
                    error="queue unavailable and QA enqueue is required",
                )
            return
        background.add_task(
            _safe_run,
            svc,
            user_id=user_id,
            project_id=project_id,
            position=position,
            level=level,
        )


async def _enqueue_resume_qa_or_fallback(
    *,
    request: Request,
    background: BackgroundTasks,
    svc: QAGenerationService,
    qa_set_id: UUID,
    user_id: UUID,
    resume_id: UUID,
    position: str,
    level: str,
) -> None:
    settings = request.app.state.settings
    queued = await enqueue_arq_job(
        settings.redis_url,
        "generate_resume_qa",
        str(user_id),
        str(resume_id),
        position,
        level,
    )
    log.info(
        "qa_generation_enqueued",
        queued=queued,
        scope="resume",
        user_id=str(user_id),
        resume_id=str(resume_id),
        position=position,
        level=level,
    )
    if not queued:
        if getattr(settings, "qa_generation_enqueue_required", False):
            async with request.app.state.db.sessionmaker() as s:
                await SqlQARepository(s).set_status(
                    qa_set_id=qa_set_id,
                    status="failed",
                    error="queue unavailable and QA enqueue is required",
                )
            return
        background.add_task(
            _safe_run_for_resume,
            svc,
            user_id=user_id,
            resume_id=resume_id,
            position=position,
            level=level,
        )


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
    ids_by_level: dict[str, UUID] = {}
    for level in body.levels:
        qa_set = await repo.get_or_create_set(
            user_id=user.id,
            project_id=project_id,
            position=body.position,
            level=level,
        )
        ids.append(qa_set.id)
        ids_by_level[level] = qa_set.id
        await repo.set_status(qa_set_id=qa_set.id, status="pending", error=None)

    svc = _service(request)
    for level in body.levels:
        await _enqueue_project_qa_or_fallback(
            request=request,
            background=background,
            svc=svc,
            qa_set_id=ids_by_level[level],
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
    return [await _set_out(SqlQARepository(session), i) for i in items]


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
    latest = await repo.latest_generation_run(qa_set_id=qa_set_id)
    return QASetDetail(
        id=qa_set.id,
        project_id=qa_set.project_id,
        resume_id=qa_set.resume_id,
        scope=qa_set.scope,
        position=qa_set.position,
        level=qa_set.level,
        status=qa_set.status,
        total=qa_set.total,
        error=qa_set.error,
        review_status=qa_set.review_status,
        review_notes=qa_set.review_notes,
        reviewed_at=qa_set.reviewed_at,
        generation_run=_run_out(latest),
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
                follow_up_axes=i.follow_up_axes or [],
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
    if qa_set.scope == "resume":
        if qa_set.resume_id is None:
            raise HTTPException(status_code=400, detail="qa set missing resume_id")
        await _enqueue_resume_qa_or_fallback(
            request=request,
            background=background,
            svc=svc,
            qa_set_id=qa_set.id,
            user_id=user.id,
            resume_id=qa_set.resume_id,
            position=qa_set.position,
            level=qa_set.level,
        )
    else:
        if qa_set.project_id is None:
            raise HTTPException(status_code=400, detail="qa set missing project_id")
        await _enqueue_project_qa_or_fallback(
            request=request,
            background=background,
            svc=svc,
            qa_set_id=qa_set.id,
            user_id=user.id,
            project_id=qa_set.project_id,
            position=qa_set.position,
            level=qa_set.level,
        )
    qa_set.status = "pending"
    qa_set.error = None
    return await _set_out(repo, qa_set)
