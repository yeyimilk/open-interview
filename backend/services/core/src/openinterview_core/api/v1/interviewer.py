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
    CreateInterviewerSessionRequest,
    InterviewEvaluationOut,
    SendInterviewerMessageRequest,
    UpdateChatSessionRequest,
)

from ...domain.interviewer import InterviewerAgent, SessionEvaluator
from ...domain.memory import MemoryDistiller, MemoryRetriever
from ...domain.projects.embedder import GatewayEmbedder
from ...domain.qa import QAGenerationService
from ...infra.db import get_session_dep
from ...infra.db.chat_repository import SqlChatRepository
from ...infra.db.qa_repository import SqlQARepository
from ...infra.db.resume_repository import SqlResumeRepository
from ..deps import get_current_user
from ..sse import sse_format

router = APIRouter(prefix="/interviewer", tags=["interviewer"])


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


def _evaluator(request: Request) -> SessionEvaluator:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return SessionEvaluator(
        sessionmaker=sm,
        gateway=request.app.state.gateway,
        retriever=_retriever(request),
    )


def _qa_service(request: Request) -> QAGenerationService:
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker
    return QAGenerationService(
        sessionmaker=sm,
        gateway=request.app.state.gateway,
        vector_store=request.app.state.vector_store,
    )


@router.post("/sessions", response_model=ChatSessionOut)
async def create_session(
    body: CreateInterviewerSessionRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> ChatSessionOut:
    import asyncio as _asyncio

    qa_repo = SqlQARepository(session)
    svc = _qa_service(request)

    target_label: str  # used in the session title
    if body.resume_id is not None:
        resume = await SqlResumeRepository(session).get(
            user_id=user.id, resume_id=body.resume_id
        )
        if resume is None:
            raise HTTPException(status_code=404, detail="resume not found")
        qa_set = await qa_repo.get_or_create_set_for_resume(
            user_id=user.id,
            resume_id=body.resume_id,
            position=body.position,
            level=body.level,
        )
        if qa_set.total == 0 and qa_set.status in ("pending", "failed"):
            _asyncio.create_task(
                svc.run_for_resume(
                    user_id=user.id,
                    resume_id=body.resume_id,
                    position=body.position,
                    level=body.level,
                )
            )
        # Trim filename for a clean title.
        fname = (resume.original_filename or "resume").rsplit(".", 1)[0][:40]
        target_label = f" — {fname}"
        target_extra = {
            "scope": "resume",
            "resume_id": str(body.resume_id),
            "resume_filename": resume.original_filename,
        }
        # Resume-scoped sessions are NOT pinned to a single project.
        session_project_id = None
    else:
        assert body.project_id is not None  # validator guarantees this
        qa_set = await qa_repo.get_or_create_set(
            user_id=user.id,
            project_id=body.project_id,
            position=body.position,
            level=body.level,
        )
        if qa_set.total == 0 and qa_set.status in ("pending", "failed"):
            _asyncio.create_task(
                svc.run(
                    user_id=user.id,
                    project_id=body.project_id,
                    position=body.position,
                    level=body.level,
                )
            )
        target_label = ""
        target_extra = {"scope": "project"}
        session_project_id = body.project_id

    chat_repo = SqlChatRepository(session)
    sess = await chat_repo.create_session(
        user_id=user.id,
        mode="interviewer",
        project_id=session_project_id,
        title=f"Mock interview ({body.position}, {body.level}){target_label}",
        target={
            "qa_set_id": str(qa_set.id),
            "position": body.position,
            "level": body.level,
            "n_questions": int(body.n_questions),
            "asked_ids": [],
            "recent_claims": [],
            "current_question": "",
            "current_ideal_answer": "",
            **target_extra,
        },
    )
    await session.commit()

    # Auto-ask the first question if the QA set already has items.
    if qa_set.total > 0:
        try:
            agent = _agent(request)
            first = await agent.turn(
                user_id=user.id,
                session_id=sess.id,
                qa_set_id=qa_set.id,
                user_input="",
                asked_ids=set(),
                prev_question="",
                prev_ideal_answer="",
            )
            if first.get("chosen_question"):
                claim_text = first.get("claim")
                claim_block = (
                    f"About this on your resume:\n> {claim_text}\n\n"
                    if claim_text
                    else ""
                )
                opening = (
                    "Welcome! Let's begin. Take your time to think through your answer.\n\n"
                    f"{claim_block}Question 1:\n{first['chosen_question']}"
                )
                await chat_repo.append_message(
                    session_id=sess.id,
                    user_id=user.id,
                    role="assistant",
                    content=opening,
                    meta={"opening": True},
                )
                row = await chat_repo.get_session(
                    user_id=user.id, session_id=sess.id
                )
                if row is not None:
                    new_target = dict(row.target or {})
                    new_target["asked_ids"] = [
                        str(i) for i in first.get("asked_ids", set())
                    ]
                    new_target["recent_claims"] = first.get(
                        "recent_claims", []
                    )
                    new_target["current_question"] = first.get(
                        "chosen_question", ""
                    )
                    new_target["current_ideal_answer"] = first.get(
                        "ideal_answer", ""
                    )
                    row.target = new_target
                await session.commit()
                # refresh the local sess view for the response
                sess = await chat_repo.get_session(
                    user_id=user.id, session_id=sess.id
                ) or sess
        except Exception:
            # Don't fail session creation if first-question prefetch fails;
            # the user can still send a message to trigger it.
            pass

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
        user_id=user.id, mode="interviewer"
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
    if sess is None or sess.mode != "interviewer":
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
    body: SendInterviewerMessageRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> StreamingResponse:
    repo = SqlChatRepository(session)
    sess = await repo.get_session(user_id=user.id, session_id=session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="not found")
    target = dict(sess.target or {})
    qa_set_id = UUID(target.get("qa_set_id")) if target.get("qa_set_id") else None
    if qa_set_id is None:
        raise HTTPException(status_code=400, detail="session missing qa_set_id")

    asked_ids = {UUID(x) for x in target.get("asked_ids", [])}
    prev_q = str(target.get("current_question") or "")
    prev_a = str(target.get("current_ideal_answer") or "")
    recent_claims = [str(c) for c in (target.get("recent_claims") or [])]

    await repo.append_message(
        session_id=session_id, user_id=user.id, role="user", content=body.content
    )

    agent = _agent(request)
    sm: async_sessionmaker[AsyncSession] = request.app.state.db.sessionmaker

    async def _gen() -> AsyncIterator[bytes]:
        chunks: list[str] = []
        meta: dict = {}
        try:
            async for ev in agent.stream(
                user_id=user.id,
                session_id=session_id,
                qa_set_id=qa_set_id,
                user_input=body.content,
                asked_ids=asked_ids,
                prev_question=prev_q,
                prev_ideal_answer=prev_a,
                recent_claims=recent_claims,
            ):
                kind = ev.get("type", "message")
                if kind == "token":
                    chunks.append(ev.get("content", ""))
                if kind == "done":
                    meta = ev.get("meta", {}) or {}
                yield sse_format(kind, ev)
        except Exception as e:
            yield sse_format("error", {"message": str(e)})
            return

        full = "".join(chunks)
        try:
            async with sm() as s:
                rrepo = SqlChatRepository(s)
                await rrepo.append_message(
                    session_id=session_id,
                    user_id=user.id,
                    role="assistant",
                    content=full,
                    meta={"evaluation": meta.get("evaluation")},
                )
                # Update session.target with new asked_ids and current Q.
                row = await rrepo.get_session(
                    user_id=user.id, session_id=session_id
                )
                if row:
                    new_target = dict(row.target or {})
                    new_target["asked_ids"] = meta.get(
                        "asked_ids", new_target.get("asked_ids", [])
                    )
                    new_target["recent_claims"] = meta.get(
                        "recent_claims", new_target.get("recent_claims", [])
                    )
                    new_target["current_question"] = meta.get("chosen_question", "")
                    new_target["current_ideal_answer"] = meta.get("ideal_answer", "")
                    row.target = new_target
                await s.commit()
        except Exception:
            pass

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.post(
    "/sessions/{session_id}:end",
    response_model=InterviewEvaluationOut,
)
async def end_session(
    session_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> InterviewEvaluationOut:
    repo = SqlChatRepository(session)
    sess = await repo.get_session(user_id=user.id, session_id=session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="not found")
    if sess.status != "ended":
        await repo.end_session(session_id=session_id)

    evaluator = _evaluator(request)
    await evaluator.evaluate(user_id=user.id, session_id=session_id)

    eval_row = await repo.get_evaluation(user_id=user.id, session_id=session_id)
    if eval_row is None:
        raise HTTPException(status_code=500, detail="evaluation failed")

    return InterviewEvaluationOut(
        id=eval_row.id,
        session_id=eval_row.session_id,
        overall_score=eval_row.overall_score,
        scores=eval_row.scores,
        summary=eval_row.summary,
        strengths=eval_row.strengths or [],
        weaknesses=eval_row.weaknesses or [],
        suggested_practice=eval_row.suggested_practice or [],
        created_at=eval_row.created_at,
    )


@router.get(
    "/sessions/{session_id}/evaluation",
    response_model=InterviewEvaluationOut,
)
async def get_evaluation(
    session_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> InterviewEvaluationOut:
    repo = SqlChatRepository(session)
    eval_row = await repo.get_evaluation(user_id=user.id, session_id=session_id)
    if eval_row is None:
        raise HTTPException(status_code=404, detail="not found")
    return InterviewEvaluationOut(
        id=eval_row.id,
        session_id=eval_row.session_id,
        overall_score=eval_row.overall_score,
        scores=eval_row.scores,
        summary=eval_row.summary,
        strengths=eval_row.strengths or [],
        weaknesses=eval_row.weaknesses or [],
        suggested_practice=eval_row.suggested_practice or [],
        created_at=eval_row.created_at,
    )
