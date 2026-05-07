"""HTTP surface for ``/general`` (a.k.a. /chat) — the workspace-aware
chat mode that mirrors the WhatsApp ``/chat`` command.

Unlike Mentor (which has the project-coach system prompt and tool loop)
and Interviewer (which is a structured turn-taking flow), /general is a
plain assistant with memory recall plus a one-line workspace brief
("you have N projects, M resumes, recent: foo, bar"). The agent layer
calls ``MentorAgent.general_stream`` so this stays in lock-step with
the messenger flow.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import User
from openinterview_schemas import (
    ChatMessageOut,
    ChatSessionOut,
    CreateGeneralSessionRequest,
    SendGeneralMessageRequest,
    UpdateChatSessionRequest,
)

from ...domain.memory import MemoryDistiller, MemoryRetriever
from ...domain.mentor import MentorAgent
from ...domain.kb import CommonKBRetriever
from ...domain.projects.embedder import GatewayEmbedder
from ...domain.workspace import workspace_brief
from ...infra.db import get_session_dep
from ...infra.db.chat_repository import SqlChatRepository
from ..deps import get_current_user
from ..sse import sse_format

router = APIRouter(prefix="/general", tags=["general"])


def _retriever(request: Request) -> MemoryRetriever:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return MemoryRetriever(
        sessionmaker=sm,
        gateway=request.app.state.gateway,
        embedder=GatewayEmbedder(request.app.state.gateway),
        vector_store=request.app.state.vector_store,
    )


def _agent(request: Request) -> MentorAgent:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return MentorAgent(
        gateway=request.app.state.gateway,
        embedder=GatewayEmbedder(request.app.state.gateway),
        vector_store=request.app.state.vector_store,
        retriever=_retriever(request),
        common_kb=CommonKBRetriever(
            sessionmaker=sm,
            gateway=request.app.state.gateway,
            vector_store=request.app.state.vector_store,
        ),
        blob=request.app.state.blob,
    )


def _distiller(request: Request) -> MemoryDistiller:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return MemoryDistiller(
        sessionmaker=sm,
        gateway=request.app.state.gateway,
        retriever=_retriever(request),
    )


@router.post("/sessions", response_model=ChatSessionOut)
async def create_session(
    body: CreateGeneralSessionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ChatSessionOut:
    sess = await SqlChatRepository(session).create_session(
        user_id=user.id,
        mode="general",
        project_id=None,
        title=body.title,
    )
    return ChatSessionOut(
        id=sess.id,
        mode=sess.mode,
        title=sess.title,
        project_id=sess.project_id,
        target=sess.target,
        status=sess.status,
        turn_count=sess.turn_count,
        created_at=sess.created_at,
    )


@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ChatSessionOut]:
    items = await SqlChatRepository(session).list_sessions(
        user_id=user.id, mode="general"
    )
    return [
        ChatSessionOut(
            id=i.id,
            mode=i.mode,
            title=i.title,
            project_id=i.project_id,
            target=i.target,
            status=i.status,
            turn_count=i.turn_count,
            created_at=i.created_at,
        )
        for i in items
    ]


@router.patch("/sessions/{session_id}", response_model=ChatSessionOut)
async def update_session(
    session_id: UUID,
    body: UpdateChatSessionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ChatSessionOut:
    repo = SqlChatRepository(session)
    sess = await repo.get_session(user_id=user.id, session_id=session_id)
    if sess is None or sess.mode != "general":
        raise HTTPException(status_code=404, detail="not found")
    updated = await repo.update_session_title(
        session_id=session_id, user_id=user.id, title=body.title
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="not found")
    return ChatSessionOut(
        id=updated.id,
        mode=updated.mode,
        title=updated.title,
        project_id=updated.project_id,
        target=updated.target,
        status=updated.status,
        turn_count=updated.turn_count,
        created_at=updated.created_at,
    )


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
async def list_messages(
    session_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ChatMessageOut]:
    repo = SqlChatRepository(session)
    sess = await repo.get_session(user_id=user.id, session_id=session_id)
    if sess is None or sess.mode != "general":
        raise HTTPException(status_code=404, detail="not found")
    items = await repo.list_messages(user_id=user.id, session_id=session_id)
    return [
        ChatMessageOut(
            id=m.id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            meta=m.meta,
            created_at=m.created_at,
        )
        for m in items
    ]


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: UUID,
    body: SendGeneralMessageRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> StreamingResponse:
    repo = SqlChatRepository(session)
    sess = await repo.get_session(user_id=user.id, session_id=session_id)
    if sess is None or sess.mode != "general":
        raise HTTPException(status_code=404, detail="not found")

    # Persist user message immediately so it shows in history.
    await repo.append_message(
        session_id=session_id, user_id=user.id, role="user", content=body.content
    )

    agent = _agent(request)
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    ws_ctx = await workspace_brief(sessionmaker=sm, user_id=user.id)

    async def _gen() -> AsyncIterator[bytes]:
        chunks: list[str] = []
        try:
            async for ev in agent.general_stream(
                user_id=user.id,
                session_id=session_id,
                workspace_brief=ws_ctx,
                user_input=body.content,
            ):
                if ev.get("type") == "token":
                    chunks.append(ev.get("content", ""))
                yield sse_format(ev.get("type", "message"), ev)
        except Exception as e:  # noqa: BLE001
            yield sse_format("error", {"message": str(e)})
            return

        full = "".join(chunks)
        try:
            async with sm() as s:
                await SqlChatRepository(s).append_message(
                    session_id=session_id,
                    user_id=user.id,
                    role="assistant",
                    content=full,
                )
        except Exception:
            # Don't break the stream if persistence fails — the user already
            # received the answer; we just lose it from history.
            pass

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.post("/sessions/{session_id}:end", response_model=ChatSessionOut)
async def end_session(
    session_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ChatSessionOut:
    repo = SqlChatRepository(session)
    sess = await repo.get_session(user_id=user.id, session_id=session_id)
    if sess is None or sess.mode != "general":
        raise HTTPException(status_code=404, detail="not found")
    await repo.end_session(session_id=session_id)

    # General chat doesn't drive an evaluation — but distilling memory is
    # cheap and lets long-term recall benefit from the conversation, so we
    # fire-and-forget the distiller exactly like Mentor's :end hook.
    import asyncio as _asyncio

    distiller = _distiller(request)
    _asyncio.create_task(distiller.distill(user_id=user.id, session_id=session_id))

    sess.status = "ended"
    return ChatSessionOut(
        id=sess.id,
        mode=sess.mode,
        title=sess.title,
        project_id=sess.project_id,
        target=sess.target,
        status="ended",
        turn_count=sess.turn_count,
        created_at=sess.created_at,
    )
