from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from openinterview_schemas import EmbeddingRequest, EmbeddingResponse

from ...domain.gateway_service import GatewayError, GatewayService
from ..deps import get_service, require_service_token

router = APIRouter(tags=["embeddings"], dependencies=[Depends(require_service_token)])


@router.post("/embeddings", response_model=EmbeddingResponse)
async def embeddings(
    req: EmbeddingRequest,
    svc: GatewayService = Depends(get_service),
) -> EmbeddingResponse:
    try:
        return await svc.embed(req)
    except GatewayError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
