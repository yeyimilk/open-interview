from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from openinterview_schemas import TranscriptionRequest, TranscriptionResponse

from ...domain.gateway_service import GatewayError, GatewayService
from ..deps import get_service, require_service_token

router = APIRouter(tags=["audio"], dependencies=[Depends(require_service_token)])


@router.post("/audio/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    req: TranscriptionRequest,
    svc: GatewayService = Depends(get_service),
) -> TranscriptionResponse:
    try:
        return await svc.transcribe(req)
    except GatewayError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
