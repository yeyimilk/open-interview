from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from openinterview_db import User

from ...infra.gateway_client.client import GatewayClientError
from ..deps import get_current_user

router = APIRouter(prefix="/audio", tags=["audio"])

_MAX_BYTES = 20 * 1024 * 1024  # 20 MB

_ALLOWED_PREFIXES = ("audio/",)


@router.post("/transcribe")
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    logical_model: str = Form(default="stt-default"),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    mime = (file.content_type or "").lower()
    if not any(mime.startswith(p) for p in _ALLOWED_PREFIXES):
        raise HTTPException(
            status_code=415,
            detail=f"unsupported audio mime: {mime or 'unknown'}",
        )

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="audio too large (limit 20MB)")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="empty audio")

    try:
        resp = await request.app.state.gateway.transcribe(
            user_id=user.id,
            logical_model=logical_model,
            audio=data,
            mime=mime,
            language=language,
        )
    except GatewayClientError as e:
        raise HTTPException(status_code=e.status, detail=str(e))

    return {"text": resp.text}
