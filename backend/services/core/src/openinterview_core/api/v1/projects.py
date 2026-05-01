from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import User
from openinterview_schemas import (
    IngestRunOut,
    ProjectDetail,
    ProjectDiagramOut,
    ProjectFileOut,
    ProjectOut,
)

from openinterview_storage import paths

from ...domain.ingestion import IngestionRunner
from ...infra.db import get_session_dep
from ...infra.db.project_repository import (
    SqlIngestRepository,
    SqlProjectRepository,
)
from ..deps import get_current_user

router = APIRouter(prefix="/projects", tags=["projects"])


def _project_zip_logical_path(user_id: UUID, project_id: UUID) -> str:
    return f"{paths.user_root(user_id)}/projects/{project_id}/source.zip"


def _runner(request: Request) -> IngestionRunner:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return IngestionRunner(
        sessionmaker=sm,
        blob=request.app.state.blob,
        vector_store=request.app.state.vector_store,
        gateway=request.app.state.gateway,
    )


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def upload_project(
    request: Request,
    background: BackgroundTasks,
    name: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ProjectOut:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="zip file required")

    repo = SqlProjectRepository(session)
    project = await repo.create(
        user_id=user.id, name=name, source_type="zip", source_uri=file.filename
    )

    data = await file.read()
    await request.app.state.blob.put_bytes(
        _project_zip_logical_path(user.id, project.id), data, content_type="application/zip"
    )

    run = await SqlIngestRepository(session).create(
        user_id=user.id, kind="project", project_id=project.id
    )

    runner = _runner(request)
    background.add_task(_safe_run, runner.run_project, user_id=user.id, project_id=project.id, run_id=run.id)

    return ProjectOut(
        id=project.id,
        name=project.name,
        source_type=project.source_type,
        status=project.status,
        summary=project.summary,
        created_at=project.created_at,
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ProjectOut]:
    items = await SqlProjectRepository(session).list(user_id=user.id)
    return [
        ProjectOut(
            id=p.id, name=p.name, source_type=p.source_type, status=p.status,
            summary=p.summary, created_at=p.created_at,
        )
        for p in items
    ]


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ProjectDetail:
    p = await SqlProjectRepository(session).get(user_id=user.id, project_id=project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="not found")
    return ProjectDetail(
        id=p.id,
        name=p.name,
        source_type=p.source_type,
        status=p.status,
        summary=p.summary,
        created_at=p.created_at,
        architecture=p.architecture,
        interesting_decisions=p.interesting_decisions,
    )


@router.get("/{project_id}/files", response_model=list[ProjectFileOut])
async def list_project_files(
    project_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ProjectFileOut]:
    items = await SqlProjectRepository(session).list_files(user_id=user.id, project_id=project_id)
    return [
        ProjectFileOut(
            id=i.id, rel_path=i.rel_path, language=i.language, bytes=i.bytes, summary=i.summary,
        )
        for i in items
    ]


@router.get("/{project_id}/diagrams", response_model=list[ProjectDiagramOut])
async def list_project_diagrams(
    project_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ProjectDiagramOut]:
    items = await SqlProjectRepository(session).list_diagrams(user_id=user.id, project_id=project_id)
    return [ProjectDiagramOut(id=i.id, name=i.name, kind=i.kind, mermaid=i.mermaid) for i in items]


@router.get("/{project_id}/runs/{run_id}", response_model=IngestRunOut)
async def get_run(
    project_id: UUID,
    run_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> IngestRunOut:
    run = await SqlIngestRepository(session).get(user_id=user.id, run_id=run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="not found")
    return IngestRunOut(
        id=run.id, kind=run.kind, status=run.status, step=run.step,
        progress=run.progress, error=run.error,
        project_id=run.project_id, resume_id=run.resume_id, created_at=run.created_at,
    )


async def _safe_run(coro_factory, **kwargs) -> None:
    try:
        await coro_factory(**kwargs)
    except Exception:
        # Errors are recorded via DbStatusReporter / runner._fail.
        pass


# Test-only: synchronous trigger so e2e tests can wait on a result.
@router.post("/{project_id}/_run_now", include_in_schema=False)
async def run_project_now(
    project_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> dict[str, str]:
    run = await SqlIngestRepository(session).create(
        user_id=user.id, kind="project", project_id=project_id
    )
    await _runner(request).run_project(user_id=user.id, project_id=project_id, run_id=run.id)
    return {"run_id": str(run.id), "status": "done"}
