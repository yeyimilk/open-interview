from __future__ import annotations

import json
from collections import defaultdict
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import User
from openinterview_logging import get_logger
from openinterview_schemas import (
    CommonKBDocumentBatchDeleteRequest,
    CommonKBDocumentBatchDeleteResponse,
    CommonKBDocumentOut,
    CommonKBItemCreate,
    CommonKBItemOut,
    CommonKBItemUpdate,
    CommonKBSourceCreate,
    CommonKBSourceOut,
    CommonKBSourceUpdate,
    CommonKBSpaceCreate,
    CommonKBSpaceOut,
    CompanyInterviewProfileOut,
)
from openinterview_storage import paths

from ...domain.kb import CommonKBProcessingService
from ...infra.db import get_session_dep
from ...infra.db.common_kb_repository import SqlCommonKBRepository
from ...infra.jobs import enqueue_arq_job
from ...infra.vector import vector_collection_for_common_kb
from ..deps import require_admin

router = APIRouter(prefix="/admin/kb", tags=["admin-kb"])
log = get_logger(__name__)


def _processor(request: Request) -> CommonKBProcessingService:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return CommonKBProcessingService(
        sessionmaker=sm,
        blob=request.app.state.blob,
        gateway=request.app.state.gateway,
        vector_store=request.app.state.vector_store,
    )


def _space_out(row) -> CommonKBSpaceOut:
    return CommonKBSpaceOut(
        id=row.id, key=row.key, name=row.name, description=row.description,
        enabled=row.enabled, created_at=row.created_at,
    )


def _source_out(row) -> CommonKBSourceOut:
    return CommonKBSourceOut(
        id=row.id, space_id=row.space_id, key=row.key, name=row.name,
        source_type=row.source_type, base_url=row.base_url, license=row.license,
        allowed_use=row.allowed_use, refresh_status=row.refresh_status,
        last_error=row.last_error, created_at=row.created_at,
    )


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    value = raw.strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()][:20]
    except json.JSONDecodeError:
        pass
    return [x.strip() for x in value.replace("\n", ",").split(",") if x.strip()][:20]


def _merge_tags(*groups: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            value = str(raw).strip()
            norm = value.lower()
            if not value or norm in seen:
                continue
            seen.add(norm)
            out.append(value)
    return out[:20]


def _document_meta_tags(row) -> list[str]:
    meta = row.meta or {}
    tags = meta.get("tags") if isinstance(meta, dict) else None
    if not isinstance(tags, list):
        return []
    return [str(t).strip() for t in tags if str(t).strip()]


def _document_create_embeddings(row) -> bool:
    meta = row.meta or {}
    if not isinstance(meta, dict):
        return True
    return bool(meta.get("create_embeddings", True))


def _doc_out(row, tags: list[str] | None = None) -> CommonKBDocumentOut:
    return CommonKBDocumentOut(
        id=row.id, space_id=row.space_id, source_id=row.source_id, title=row.title,
        filename=row.filename, content_type=row.content_type, blob_path=row.blob_path,
        canonical_url=row.canonical_url, content_hash=row.content_hash,
        status=row.status, error=row.error, meta=row.meta,
        tags=_merge_tags(_document_meta_tags(row), tags or []),
        create_embeddings=_document_create_embeddings(row),
        created_at=row.created_at,
    )


async def _item_out(repo: SqlCommonKBRepository, row) -> CommonKBItemOut:
    tags = await repo.item_tags([row.id])
    return CommonKBItemOut(
        id=row.id, space_id=row.space_id, source_id=row.source_id,
        document_id=row.document_id, item_type=row.item_type,
        category=row.category, title=row.title, question=row.question,
        answer_outline=row.answer_outline, content=row.content,
        difficulty=row.difficulty, role_family=row.role_family, level=row.level,
        company=row.company, language=row.language, provenance=row.provenance,
        status=row.status, version=row.version, tags=tags.get(row.id, []),
        created_at=row.created_at,
    )


@router.post("/spaces", response_model=CommonKBSpaceOut, status_code=status.HTTP_201_CREATED)
async def create_space(
    body: CommonKBSpaceCreate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> CommonKBSpaceOut:
    row = await SqlCommonKBRepository(session).get_or_create_space(
        key=body.key, name=body.name, description=body.description, enabled=body.enabled
    )
    return _space_out(row)


@router.get("/spaces", response_model=list[CommonKBSpaceOut])
async def list_spaces(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> list[CommonKBSpaceOut]:
    return [_space_out(r) for r in await SqlCommonKBRepository(session).list_spaces()]


@router.post("/sources", response_model=CommonKBSourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: CommonKBSourceCreate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> CommonKBSourceOut:
    repo = SqlCommonKBRepository(session)
    space = await repo.get_space_by_key(body.space_key)
    if space is None:
        raise HTTPException(status_code=404, detail="space not found")
    row = await repo.create_source(
        space_id=space.id, key=body.key, name=body.name,
        source_type=body.source_type, base_url=body.base_url,
        license=body.license, allowed_use=body.allowed_use,
    )
    return _source_out(row)


@router.get("/sources", response_model=list[CommonKBSourceOut])
async def list_sources(
    space: str | None = None,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> list[CommonKBSourceOut]:
    return [_source_out(r) for r in await SqlCommonKBRepository(session).list_sources(space_key=space)]


@router.patch("/sources/{source_id}", response_model=CommonKBSourceOut)
async def update_source(
    source_id: UUID,
    body: CommonKBSourceUpdate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> CommonKBSourceOut:
    row = await SqlCommonKBRepository(session).update_source(
        source_id, **body.model_dump(exclude_unset=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _source_out(row)


@router.post("/documents", response_model=CommonKBDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    space_key: str = Form(...),
    source_id: UUID | None = Form(default=None),
    title: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    create_embeddings: bool = Form(default=True),
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> CommonKBDocumentOut:
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")
    repo = SqlCommonKBRepository(session)
    space = await repo.get_space_by_key(space_key)
    if space is None:
        raise HTTPException(status_code=404, detail="space not found")
    doc = await repo.create_document(
        space_id=space.id,
        source_id=source_id,
        title=title or file.filename,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        blob_path=None,
        meta={"tags": _parse_tags(tags), "create_embeddings": create_embeddings},
    )
    data = await file.read()
    blob_name = file.filename.rsplit("/", 1)[-1]
    blob_path = paths.common_kb_document(doc.id, blob_name)
    await request.app.state.blob.put_bytes(blob_path, data, content_type=file.content_type)
    doc = await repo.update_document(doc.id, blob_path=blob_path)
    return _doc_out(doc)


@router.get("/documents", response_model=list[CommonKBDocumentOut])
async def list_documents(
    space: str | None = None,
    status: str | None = None,
    limit: int = 100,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> list[CommonKBDocumentOut]:
    repo = SqlCommonKBRepository(session)
    rows = await repo.list_documents(space_key=space, status=status, limit=limit)
    tag_map = await repo.document_tags([r.id for r in rows])
    return [_doc_out(r, tag_map.get(r.id, [])) for r in rows]


@router.get("/documents/{document_id}", response_model=CommonKBDocumentOut)
async def get_document(
    document_id: UUID,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> CommonKBDocumentOut:
    repo = SqlCommonKBRepository(session)
    row = await repo.get_document(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    tag_map = await repo.document_tags([row.id])
    return _doc_out(row, tag_map.get(row.id, []))


async def _delete_document_and_artifacts(
    document_id: UUID,
    request: Request,
    repo: SqlCommonKBRepository,
) -> bool:
    row = await repo.get_document(document_id)
    if row is None:
        return False
    blob_path = row.blob_path
    item_refs = await repo.document_item_refs(document_id)
    deleted = await repo.delete_document_with_items(document_id)
    if not deleted:
        return False
    ids_by_space: dict[str, list[str]] = defaultdict(list)
    for item_id, space_key in item_refs:
        ids_by_space[space_key].append(str(item_id))
    for space_key, item_ids in ids_by_space.items():
        try:
            await request.app.state.vector_store.delete(
                collection=vector_collection_for_common_kb(space_key),
                ids=item_ids,
            )
        except Exception as e:  # noqa: BLE001
            log.warning(
                "common_kb_delete_vectors_failed",
                document_id=str(document_id),
                space_key=space_key,
                error=str(e),
            )
    if blob_path:
        try:
            await request.app.state.blob.delete(blob_path)
        except Exception as e:  # noqa: BLE001
            log.warning("common_kb_delete_blob_failed", document_id=str(document_id), error=str(e))
    return True


@router.post("/documents:batch-delete", response_model=CommonKBDocumentBatchDeleteResponse)
async def batch_delete_documents(
    body: CommonKBDocumentBatchDeleteRequest,
    request: Request,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> CommonKBDocumentBatchDeleteResponse:
    repo = SqlCommonKBRepository(session)
    deleted_ids: list[UUID] = []
    missing_ids: list[UUID] = []
    seen: set[UUID] = set()
    for document_id in body.document_ids:
        if document_id in seen:
            continue
        seen.add(document_id)
        deleted = await _delete_document_and_artifacts(document_id, request, repo)
        if deleted:
            deleted_ids.append(document_id)
        else:
            missing_ids.append(document_id)
    return CommonKBDocumentBatchDeleteResponse(
        deleted_ids=deleted_ids,
        missing_ids=missing_ids,
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    request: Request,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> None:
    deleted = await _delete_document_and_artifacts(
        document_id,
        request,
        SqlCommonKBRepository(session),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="not found")


@router.post("/documents/{document_id}:process")
async def process_document(
    document_id: UUID,
    background: BackgroundTasks,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict[str, str]:
    settings = request.app.state.settings
    queued = await enqueue_arq_job(
        settings.redis_url, "process_common_kb_document", str(document_id), str(admin.id)
    )
    if not queued:
        background.add_task(_processor(request).process_document, document_id=document_id, actor_user_id=admin.id)
    return {"status": "queued" if queued else "background"}


@router.post("/items", response_model=CommonKBItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    body: CommonKBItemCreate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> CommonKBItemOut:
    repo = SqlCommonKBRepository(session)
    space = await repo.get_space_by_key(body.space_key)
    if space is None:
        raise HTTPException(status_code=404, detail="space not found")
    row = await repo.create_item(
        space_id=space.id,
        source_id=body.source_id,
        document_id=body.document_id,
        item_type=body.item_type,
        category=body.category,
        title=body.title,
        question=body.question,
        answer_outline=body.answer_outline,
        content=body.content,
        difficulty=body.difficulty,
        role_family=body.role_family,
        level=body.level,
        company=body.company,
        language=body.language,
        provenance=body.provenance,
        tags=body.tags,
        status=body.status,
    )
    await _processor(request).embed_items(item_ids=[row.id], actor_user_id=admin.id)
    return await _item_out(repo, row)


@router.get("/items", response_model=list[CommonKBItemOut])
async def list_items(
    space: str | None = None,
    tag: str | None = None,
    company: str | None = None,
    category: str | None = None,
    language: str | None = None,
    limit: int = 100,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> list[CommonKBItemOut]:
    repo = SqlCommonKBRepository(session)
    rows = await repo.list_items(
        space_key=space,
        tag=tag,
        company=company,
        category=category,
        language=language,
        limit=limit,
    )
    return [await _item_out(repo, r) for r in rows]


@router.patch("/items/{item_id}", response_model=CommonKBItemOut)
async def update_item(
    item_id: UUID,
    body: CommonKBItemUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> CommonKBItemOut:
    repo = SqlCommonKBRepository(session)
    data = body.model_dump(exclude_unset=True)
    tags = data.pop("tags", None)
    row = await repo.update_item(item_id, tags=tags, **data)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    await _processor(request).embed_items(item_ids=[row.id], actor_user_id=admin.id)
    return await _item_out(repo, row)


@router.post("/sources/{source_id}:refresh")
async def refresh_source(
    source_id: UUID,
    background: BackgroundTasks,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict[str, str]:
    settings = request.app.state.settings
    queued = await enqueue_arq_job(
        settings.redis_url, "refresh_common_kb_source", str(source_id), str(admin.id)
    )
    if not queued:
        background.add_task(_processor(request).refresh_source, source_id=source_id, actor_user_id=admin.id)
    return {"status": "queued" if queued else "background"}


@router.post("/company-profiles:rebuild")
async def rebuild_profiles(
    background: BackgroundTasks,
    request: Request,
    company_key: str | None = None,
    _: User = Depends(require_admin),
) -> dict[str, str]:
    settings = request.app.state.settings
    queued = await enqueue_arq_job(
        settings.redis_url, "rebuild_company_interview_profiles", company_key
    )
    if not queued:
        background.add_task(_processor(request).rebuild_company_profiles, company_key=company_key)
    return {"status": "queued" if queued else "background"}
