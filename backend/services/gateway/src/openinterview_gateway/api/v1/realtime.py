from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from openinterview_schemas import (
    RealtimeTranscriptionSessionRequest,
    RealtimeTranscriptionSessionResponse,
)

from ...domain.gateway_service import GatewayError, GatewayService
from ..deps import get_service, require_service_token

router = APIRouter(tags=["realtime"], dependencies=[Depends(require_service_token)])


@router.post(
    "/realtime/transcription/session",
    response_model=RealtimeTranscriptionSessionResponse,
)
async def create_realtime_transcription_session(
    req: RealtimeTranscriptionSessionRequest,
    svc: GatewayService = Depends(get_service),
) -> RealtimeTranscriptionSessionResponse:
    try:
        return await svc.create_realtime_transcription_session(req)
    except GatewayError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
