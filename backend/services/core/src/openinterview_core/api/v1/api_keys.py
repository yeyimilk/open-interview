from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import User
from openinterview_schemas import ApiKeyOut, CreateApiKeyRequest

from ...domain.api_keys import ApiKeyService
from ...infra.db import get_session_dep
from ...infra.db.api_key_repository import SqlApiKeyRepository
from ..deps import get_current_user

router = APIRouter(prefix="/me/api-keys", tags=["api-keys"])


def _service(request: Request, session: AsyncSession) -> ApiKeyService:
    secret_box = request.app.state.secret_box
    return ApiKeyService(repo=SqlApiKeyRepository(session), encrypt=secret_box.encrypt)


@router.post("", response_model=ApiKeyOut, status_code=status.HTTP_201_CREATED)
async def add_key(
    req: CreateApiKeyRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ApiKeyOut:
    out = await _service(request, session).add(
        user_id=user.id, provider=req.provider, label=req.label, plaintext=req.plaintext
    )
    return ApiKeyOut(id=out.id, provider=out.provider, label=out.label, created_at=out.created_at)


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ApiKeyOut]:
    items = await _service(request, session).list(user_id=user.id)
    return [
        ApiKeyOut(id=i.id, provider=i.provider, label=i.label, created_at=i.created_at)
        for i in items
    ]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    key_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> None:
    ok = await _service(request, session).delete(user_id=user.id, key_id=key_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
