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
    CreateMentorSessionRequest,
    SendMentorMessageRequest,
    UpdateChatSessionRequest,
)

from ...domain.memory import MemoryDistiller, MemoryRetriever
from ...domain.mentor import MentorAgent
from ...domain.projects.embedder import GatewayEmbedder
from ...infra.db import get_session_dep
from ...infra.db.chat_repository import SqlChatRepository
from ..deps import get_current_user
from ..sse import sse_format

router = APIRouter(prefix="/mentor", tags=["mentor"])


def _retriever(request: Request) -> MemoryRetriever:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return MemoryRetriever(
        sessionmaker=sm,
        gateway=request.app.state.gateway,
        embedder=GatewayEmbedder(request.app.state.gateway),
        vector_store=request.app.state.vector_store,
    )


def _agent(request: Request) -> MentorAgent:
    return MentorAgent(
        gateway=request.app.state.gateway,
        retrieval_service=request.app.state.retrieval_service,
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
    body: CreateMentorSessionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ChatSessionOut:
    sess = await SqlChatRepository(session).create_session(
        user_id=user.id,
        mode="mentor",
        project_id=body.project_id,
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
        user_id=user.id, mode="mentor"
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
    if sess is None or sess.mode != "mentor":
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
    if sess is None:
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
    body: SendMentorMessageRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> StreamingResponse:
    repo = SqlChatRepository(session)
    sess = await repo.get_session(user_id=user.id, session_id=session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="not found")

    # Persist user message immediately so it shows in history.
    await repo.append_message(
        session_id=session_id, user_id=user.id, role="user", content=body.content
    )

    project_id = body.project_id or sess.project_id
    agent = _agent(request)
    distiller = _distiller(request)

    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker

    async def _gen() -> AsyncIterator[bytes]:
        chunks: list[str] = []
        tool_trace: list[dict] = []
        try:
            async for ev in agent.stream(
                user_id=user.id,
                session_id=session_id,
                project_id=project_id,
                user_input=body.content,
            ):
                kind = ev.get("type", "message")
                if kind == "token":
                    chunks.append(ev.get("content", ""))
                elif kind == "tool_call":
                    tool_trace.append(
                        {
                            "name": ev.get("name", ""),
                            "args": ev.get("args"),
                            "preview": None,
                            "done": False,
                        }
                    )
                elif kind == "tool_result":
                    name = ev.get("name", "")
                    preview = ev.get("preview")
                    # attach to the most recent matching un-done call
                    for entry in reversed(tool_trace):
                        if entry["name"] == name and not entry["done"]:
                            entry["preview"] = preview
                            entry["done"] = True
                            break
                yield sse_format(kind, ev)
        except Exception as e:
            yield sse_format("error", {"message": str(e)})
            return

        full = "".join(chunks)
        meta: dict | None = {"tools": tool_trace} if tool_trace else None
        # Persist assistant message + (best-effort) update long-term memory.
        try:
            async with sm() as s:
                await SqlChatRepository(s).append_message(
                    session_id=session_id,
                    user_id=user.id,
                    role="assistant",
                    content=full,
                    meta=meta,
                )
            # Distillation happens explicitly when the user ends the session.
        except Exception:
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
    if sess is None:
        raise HTTPException(status_code=404, detail="not found")
    await repo.end_session(session_id=session_id)

    # Fire-and-forget memory distillation.
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
