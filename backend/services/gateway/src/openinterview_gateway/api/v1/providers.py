from fastapi import APIRouter, Depends, HTTPException, Query

from openinterview_schemas import (
    ProviderModelList,
    ProviderTestRequest,
    ProviderTestResponse,
)

from ...domain.gateway_service import GatewayError, GatewayService
from ..deps import get_service, require_service_token

router = APIRouter(tags=["providers"], dependencies=[Depends(require_service_token)])


@router.get("/providers/{provider}/models", response_model=ProviderModelList)
async def list_provider_models(
    provider: str,
    user_id: str = Query(...),
    endpoint: str = Query(...),
    svc: GatewayService = Depends(get_service),
) -> ProviderModelList:
    from uuid import UUID

    try:
        uid = UUID(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid user_id: {e}")
    try:
        return await svc.list_provider_models(
            user_id=uid, provider=provider, endpoint=endpoint
        )
    except GatewayError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.post("/providers/test", response_model=ProviderTestResponse)
async def test_provider(
    req: ProviderTestRequest,
    svc: GatewayService = Depends(get_service),
) -> ProviderTestResponse:
    try:
        return await svc.test_provider(req)
    except GatewayError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
