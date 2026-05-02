from __future__ import annotations

from uuid import UUID  # noqa: F401

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import User
from openinterview_schemas import (
    ModelPreferenceOut,
    ModelRole,
    ProviderModelList,
    ProviderTestRequest,
    ProviderTestResponse,
    UpdateModelPreferenceRequest,
)

from ...infra.db import get_session_dep
from ...infra.db.user_model_preference_repository import (
    SqlUserModelPreferenceRepository,
)
from ..deps import get_current_user

router = APIRouter(prefix="/me/model-preferences", tags=["model-preferences"])

_VALID_ROLES = ("chat", "embedding", "transcription", "voice-analysis")


def _to_out(row) -> ModelPreferenceOut:
    return ModelPreferenceOut(
        role=row.role,
        provider=row.provider,
        endpoint=row.endpoint,
        model_id=row.model_id,
        updated_at=getattr(row, "updated_at", None),
    )


@router.get("", response_model=list[ModelPreferenceOut])
async def list_preferences(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ModelPreferenceOut]:
    rows = await SqlUserModelPreferenceRepository(session).list_for_user(
        user_id=user.id
    )
    return [_to_out(r) for r in rows]


@router.put("/{role}", response_model=ModelPreferenceOut)
async def upsert_preference(
    role: ModelRole,
    body: UpdateModelPreferenceRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ModelPreferenceOut:
    if role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"unknown role: {role}")
    row = await SqlUserModelPreferenceRepository(session).upsert(
        user_id=user.id,
        role=role,
        provider=body.provider.strip(),
        endpoint=body.endpoint.strip(),
        model_id=body.model_id.strip(),
    )
    return _to_out(row)


@router.delete("/{role}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preference(
    role: ModelRole,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> None:
    if role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"unknown role: {role}")
    await SqlUserModelPreferenceRepository(session).delete(
        user_id=user.id, role=role
    )


@router.post("/{role}/test", response_model=ProviderTestResponse)
async def test_preference(
    role: ModelRole,
    body: UpdateModelPreferenceRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> ProviderTestResponse:
    """Validate a (role, provider, endpoint, model_id) by performing a
    tiny round-trip via the gateway."""
    if role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"unknown role: {role}")
    return await request.app.state.gateway.test_provider(
        user_id=user.id,
        role=role,
        provider=body.provider.strip(),
        endpoint=body.endpoint.strip(),
        model_id=body.model_id.strip(),
    )


providers_router = APIRouter(prefix="/providers", tags=["providers"])


@providers_router.get(
    "/{provider}/models", response_model=ProviderModelList
)
async def list_provider_models(
    provider: str,
    request: Request,
    endpoint: str = Query(...),
    user: User = Depends(get_current_user),
) -> ProviderModelList:
    return await request.app.state.gateway.list_provider_models(
        user_id=user.id, provider=provider, endpoint=endpoint
    )
