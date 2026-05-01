from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from openinterview_schemas import ChatCompletionRequest, ChatCompletionResponse

from ...domain.gateway_service import GatewayError, GatewayService
from ..deps import get_service, require_service_token

router = APIRouter(tags=["chat"], dependencies=[Depends(require_service_token)])


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    req: ChatCompletionRequest,
    svc: GatewayService = Depends(get_service),
) -> ChatCompletionResponse:
    try:
        return await svc.chat(req)
    except GatewayError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


def _sse(event: str, data: object) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode(
        "utf-8"
    )


@router.post("/chat/completions/stream")
async def chat_completions_stream(
    req: ChatCompletionRequest,
    svc: GatewayService = Depends(get_service),
) -> StreamingResponse:
    async def _gen() -> AsyncIterator[bytes]:
        try:
            async for piece in svc.chat_stream(req):
                yield _sse("delta", {"content": piece})
        except GatewayError as e:
            yield _sse("error", {"message": str(e), "status": e.status})
            return
        except Exception as e:  # noqa: BLE001
            yield _sse("error", {"message": str(e)})
            return
        yield _sse("done", {})

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
