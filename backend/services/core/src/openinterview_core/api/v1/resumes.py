from __future__ import annotations

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
from fastapi.responses import Response
from urllib.parse import quote
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import User
from openinterview_schemas import ClaimMappingOut, IngestRunOut, ResumeDetail, ResumeOut
from openinterview_storage import paths

from ...domain.ingestion import IngestionRunner
from ...domain.resumes import ResumeTextExtractor
from ...infra.db import get_session_dep
from ...infra.db.project_repository import SqlIngestRepository
from ...infra.db.resume_repository import SqlResumeRepository
from ..deps import get_current_user
from .projects import _safe_run

router = APIRouter(prefix="/resumes", tags=["resumes"])


def _runner(request: Request) -> IngestionRunner:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return IngestionRunner(
        sessionmaker=sm,
        blob=request.app.state.blob,
        vector_store=request.app.state.vector_store,
        gateway=request.app.state.gateway,
    )


@router.post("", response_model=ResumeOut, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    project_ids: str = Form(default=""),  # comma-separated UUIDs
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ResumeOut:
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")

    data = await file.read()
    text = ResumeTextExtractor().extract(
        filename=file.filename, content_type=file.content_type or "", data=data
    )

    repo = SqlResumeRepository(session)
    resume = await repo.create(
        user_id=user.id,
        original_filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        text=text,
    )

    # Persist original blob for audit/export.
    ext = (file.filename.rsplit(".", 1)[-1] or "bin").lower()
    await request.app.state.blob.put_bytes(
        paths.resume_original(user.id, resume.id, ext), data
    )

    run = await SqlIngestRepository(session).create(
        user_id=user.id, kind="resume", resume_id=resume.id
    )

    pids = [UUID(p.strip()) for p in project_ids.split(",") if p.strip()]
    background.add_task(
        _safe_run,
        _runner(request).run_resume,
        user_id=user.id,
        resume_id=resume.id,
        run_id=run.id,
        project_ids=pids,
    )

    return ResumeOut(
        id=resume.id,
        original_filename=resume.original_filename,
        content_type=resume.content_type,
        created_at=resume.created_at,
    )


@router.get("", response_model=list[ResumeOut])
async def list_resumes(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ResumeOut]:
    items = await SqlResumeRepository(session).list_for_user(user_id=user.id)
    return [
        ResumeOut(
            id=r.id,
            original_filename=r.original_filename,
            content_type=r.content_type,
            created_at=r.created_at,
        )
        for r in items
    ]


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> None:
    ok = await SqlResumeRepository(session).delete(
        user_id=user.id, resume_id=resume_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="not found")


@router.get("/{resume_id}", response_model=ResumeDetail)
async def get_resume(
    resume_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ResumeDetail:
    r = await SqlResumeRepository(session).get(user_id=user.id, resume_id=resume_id)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return ResumeDetail(
        id=r.id,
        original_filename=r.original_filename,
        content_type=r.content_type,
        created_at=r.created_at,
        text=r.text,
        parsed=r.parsed,
    )


@router.get("/{resume_id}/file")
async def download_resume_file(
    resume_id: UUID,
    request: Request,
    inline: bool = True,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> Response:
    r = await SqlResumeRepository(session).get(user_id=user.id, resume_id=resume_id)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")

    ext = (r.original_filename.rsplit(".", 1)[-1] or "bin").lower()
    try:
        data = await request.app.state.blob.get_bytes(
            paths.resume_original(user.id, resume_id, ext)
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="file not found") from exc

    disposition = "inline" if inline else "attachment"
    fname = quote(r.original_filename)
    return Response(
        content=data,
        media_type=r.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{fname}",
            "Cache-Control": "private, max-age=60",
        },
    )


@router.get("/{resume_id}/claim-mappings", response_model=list[ClaimMappingOut])
async def list_claim_mappings(
    resume_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ClaimMappingOut]:
    items = await SqlResumeRepository(session).list_mappings(user_id=user.id, resume_id=resume_id)
    return [
        ClaimMappingOut(
            id=i.id,
            claim=i.claim,
            project_id=i.project_id,
            grounding=i.grounding,
            confidence=i.confidence,
        )
        for i in items
    ]


@router.get("/{resume_id}/runs/{run_id}", response_model=IngestRunOut)
async def get_resume_run(
    resume_id: UUID,
    run_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> IngestRunOut:
    run = await SqlIngestRepository(session).get(user_id=user.id, run_id=run_id)
    if run is None or run.resume_id != resume_id:
        raise HTTPException(status_code=404, detail="not found")
    return IngestRunOut(
        id=run.id, kind=run.kind, status=run.status, step=run.step,
        progress=run.progress, error=run.error,
        project_id=run.project_id, resume_id=run.resume_id, created_at=run.created_at,
    )


# Test-only synchronous trigger.
@router.post("/{resume_id}/_run_now", include_in_schema=False)
async def run_resume_now(
    resume_id: UUID,
    request: Request,
    project_ids: str = "",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> dict[str, str]:
    run = await SqlIngestRepository(session).create(
        user_id=user.id, kind="resume", resume_id=resume_id
    )
    pids = [UUID(p.strip()) for p in project_ids.split(",") if p.strip()]
    await _runner(request).run_resume(
        user_id=user.id, resume_id=resume_id, run_id=run.id, project_ids=pids
    )
    return {"run_id": str(run.id), "status": "done"}
