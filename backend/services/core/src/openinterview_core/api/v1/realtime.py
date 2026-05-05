"""Realtime (live-audio) integration endpoints.

Two surfaces:
  * Public (user JWT): mints a short-lived ticket the browser uses to upgrade
    to the realtime gateway's WebSocket. The realtime gateway URL is read
    from settings, never hard-coded in the browser.
  * Internal (service token): runs an interviewer turn from a pre-transcribed
    user utterance. Mirrors the logic in `interviewer.send_audio_message` but
    skips the STT step (the realtime gateway has already done it).
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import User
from openinterview_schemas import ChatMessageOut

from ...domain.interviewer import InterviewerAgent
from ...domain.memory import MemoryRetriever
from ...domain.projects.embedder import GatewayEmbedder
from ...infra.db import get_session_dep
from ...infra.db.chat_repository import SqlChatRepository
from ..deps import get_current_user
from ..sse import sse_format

router = APIRouter(tags=["realtime"])


class RealtimeTicketOut(BaseModel):
    ws_url: str
    ticket: str
    expires_at: int


@router.post(
    "/interviewer/sessions/{session_id}/realtime/ticket",
    response_model=RealtimeTicketOut,
)
async def mint_realtime_ticket(
    session_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> RealtimeTicketOut:
    repo = SqlChatRepository(session)
    sess = await repo.get_session(user_id=user.id, session_id=session_id)
    if sess is None or sess.mode != "interviewer":
        raise HTTPException(status_code=404, detail="not found")
    if sess.status == "ended":
        raise HTTPException(status_code=400, detail="session ended")
    s = request.app.state.settings
    exp = int(time.time()) + int(s.realtime_ticket_ttl_s)
    payload = {
        "sub": str(user.id),
        "sid": str(session_id),
        "mode": "interviewer",
        "exp": exp,
    }
    ticket = jwt.encode(
        payload, s.openinterview_realtime_secret, algorithm="HS256"
    )
    return RealtimeTicketOut(
        ws_url=s.realtime_public_url, ticket=ticket, expires_at=exp
    )


# ----------------------- internal -----------------------


class _InternalTurnBody(BaseModel):
    user_id: UUID
    transcript: str
    voice: dict | None = None


def _retriever(request: Request) -> MemoryRetriever:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return MemoryRetriever(
        sessionmaker=sm,
        gateway=request.app.state.gateway,
        embedder=GatewayEmbedder(request.app.state.gateway),
        vector_store=request.app.state.vector_store,
    )


def _agent(request: Request) -> InterviewerAgent:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return InterviewerAgent(
        sessionmaker=sm,
        gateway=request.app.state.gateway,
        retriever=_retriever(request),
    )


def _require_internal(
    request: Request,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    expected = request.app.state.settings.realtime_internal_token
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="invalid internal token")


@router.post(
    "/internal/interviewer/{session_id}/turn",
    response_model=None,
    dependencies=[Depends(_require_internal)],
)
async def internal_interviewer_turn(
    session_id: UUID,
    body: _InternalTurnBody,
    request: Request,
    session: AsyncSession = Depends(get_session_dep),
) -> StreamingResponse:
    repo = SqlChatRepository(session)
    sess = await repo.get_session(user_id=body.user_id, session_id=session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="not found")
    target = dict(sess.target or {})
    qa_set_id = (
        UUID(target.get("qa_set_id")) if target.get("qa_set_id") else None
    )
    if qa_set_id is None:
        raise HTTPException(status_code=400, detail="session missing qa_set_id")

    asked_ids = {UUID(x) for x in target.get("asked_ids", [])}
    prev_q = str(target.get("current_question") or "")
    prev_a = str(target.get("current_ideal_answer") or "")
    recent_claims = [str(c) for c in (target.get("recent_claims") or [])]

    transcript = (body.transcript or "").strip()
    if not transcript:
        raise HTTPException(status_code=422, detail="empty transcript")
    voice = body.voice or {}

    await repo.append_message(
        session_id=session_id,
        user_id=body.user_id,
        role="user",
        content=transcript,
        meta={"voice": voice, "channel": "live"} if voice else {"channel": "live"},
    )

    agent = _agent(request)
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker

    async def _gen() -> AsyncIterator[bytes]:
        chunks: list[str] = []
        meta: dict[str, Any] = {}
        try:
            async for ev in agent.stream(
                user_id=body.user_id,
                session_id=session_id,
                qa_set_id=qa_set_id,
                user_input=transcript,
                asked_ids=asked_ids,
                prev_question=prev_q,
                prev_ideal_answer=prev_a,
                recent_claims=recent_claims,
                voice_features=voice or None,
            ):
                kind = ev.get("type", "message")
                if kind == "token":
                    chunks.append(ev.get("content", ""))
                if kind == "done":
                    meta = ev.get("meta", {}) or {}
                yield sse_format(kind, ev)
        except Exception as e:  # noqa: BLE001
            yield sse_format("error", {"message": str(e)})
            return

        full = "".join(chunks)
        try:
            async with sm() as s:
                rrepo = SqlChatRepository(s)
                await rrepo.append_message(
                    session_id=session_id,
                    user_id=body.user_id,
                    role="assistant",
                    content=full,
                    meta={
                        "evaluation": meta.get("evaluation"),
                        "channel": "live",
                    },
                )
                row = await rrepo.get_session(
                    user_id=body.user_id, session_id=session_id
                )
                if row:
                    new_target = dict(row.target or {})
                    new_target["asked_ids"] = meta.get(
                        "asked_ids", new_target.get("asked_ids", [])
                    )
                    new_target["recent_claims"] = meta.get(
                        "recent_claims", new_target.get("recent_claims", [])
                    )
                    new_target["current_question"] = meta.get(
                        "chosen_question", ""
                    )
                    new_target["current_ideal_answer"] = meta.get(
                        "ideal_answer", ""
                    )
                    row.target = new_target
                await s.commit()
        except Exception:
            pass

    return StreamingResponse(_gen(), media_type="text/event-stream")


# Make the import lints happy (re-exporting for IDEs).
__all__ = ["router", "RealtimeTicketOut", "ChatMessageOut"]
