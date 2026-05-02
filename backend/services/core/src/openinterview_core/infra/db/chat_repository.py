from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import (
    ChatMessage,
    ChatSession,
    InterviewEvaluation,
)


def _derive_title(text: str, *, max_chars: int = 60) -> str:
    """Make a short title from a free-form first message.

    Take the first line, collapse internal whitespace, strip a leading
    slash-command (so "/help me debug" becomes "help me debug"), and
    truncate at the nearest word boundary up to ``max_chars`` with a
    trailing ellipsis.
    """
    first_line = next(
        (line for line in text.splitlines() if line.strip()),
        "",
    )
    s = " ".join(first_line.split())
    if s.startswith("/"):
        # The grammar uses leading slash for commands — for free-form chat
        # we don't want titles like "/help me debug" / "/please explain".
        s = s.lstrip("/").strip()
    if not s:
        return "Untitled"
    if len(s) <= max_chars:
        return s
    cut = s.rfind(" ", 0, max_chars)
    if cut < 20:  # word boundary too close to the start; hard-cut instead
        cut = max_chars
    return s[:cut].rstrip() + "…"


class SqlChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create_session(
        self,
        *,
        user_id: UUID,
        mode: str,
        project_id: UUID | None = None,
        title: str | None = None,
        target: dict | None = None,
    ) -> ChatSession:
        row = ChatSession(
            user_id=user_id,
            mode=mode,
            project_id=project_id,
            title=title,
            target=target,
            status="active",
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def get_session(
        self, *, user_id: UUID, session_id: UUID
    ) -> ChatSession | None:
        q = select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user_id
        )
        return (await self._s.execute(q)).scalar_one_or_none()

    async def list_sessions(
        self, *, user_id: UUID, mode: str | None = None
    ) -> list[ChatSession]:
        q = select(ChatSession).where(ChatSession.user_id == user_id)
        if mode:
            q = q.where(ChatSession.mode == mode)
        q = q.order_by(ChatSession.created_at.desc())
        return list((await self._s.execute(q)).scalars())

    async def end_session(self, *, session_id: UUID) -> None:
        row = await self._s.get(ChatSession, session_id)
        if row:
            row.status = "ended"
            await self._s.commit()

    async def append_message(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        role: str,
        content: str,
        meta: dict | None = None,
    ) -> ChatMessage:
        row = ChatMessage(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            meta=meta,
        )
        self._s.add(row)
        sess = await self._s.get(ChatSession, session_id)
        if sess:
            sess.turn_count = (sess.turn_count or 0) + 1
            # Auto-title on the first user message: pick a short, sensible
            # snippet of `content`. Users can rename via the PATCH endpoint
            # later. We deliberately only trigger when the title is still
            # NULL — once the user (or the agent that created the session)
            # has set a title we never silently overwrite it.
            if role == "user" and not sess.title and content.strip():
                sess.title = _derive_title(content)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def update_session_title(
        self, *, session_id: UUID, user_id: UUID, title: str | None
    ) -> ChatSession | None:
        """Rename a session. ``title=None`` clears it back to "Untitled"."""
        row = await self._s.get(ChatSession, session_id)
        if row is None or row.user_id != user_id:
            return None
        # Normalise: strip whitespace, cap to a sane length, treat empty as None.
        if title is not None:
            title = title.strip()[:256] or None
        row.title = title
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def list_messages(
        self, *, user_id: UUID, session_id: UUID, limit: int | None = None
    ) -> list[ChatMessage]:
        q = (
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.user_id == user_id,
            )
            .order_by(ChatMessage.created_at.asc())
        )
        if limit:
            q = q.limit(limit)
        return list((await self._s.execute(q)).scalars())

    async def save_evaluation(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        overall_score: float,
        scores: dict,
        summary: str,
        strengths: list,
        weaknesses: list,
        suggested_practice: list,
    ) -> InterviewEvaluation:
        row = InterviewEvaluation(
            session_id=session_id,
            user_id=user_id,
            overall_score=overall_score,
            scores=scores,
            summary=summary,
            strengths=strengths,
            weaknesses=weaknesses,
            suggested_practice=suggested_practice,
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def get_evaluation(
        self, *, user_id: UUID, session_id: UUID
    ) -> InterviewEvaluation | None:
        q = (
            select(InterviewEvaluation)
            .where(
                InterviewEvaluation.session_id == session_id,
                InterviewEvaluation.user_id == user_id,
            )
            .order_by(InterviewEvaluation.created_at.desc())
        )
        return (await self._s.execute(q)).scalars().first()
