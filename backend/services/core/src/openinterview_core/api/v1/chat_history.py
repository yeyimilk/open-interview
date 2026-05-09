from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import User
from openinterview_schemas import ChatHistorySearchResult, ChatSessionOut

from ...infra.db import get_session_dep
from ...infra.db.chat_repository import SqlChatRepository
from ..deps import get_current_user

router = APIRouter(prefix="/chat-history", tags=["chat-history"])


@router.get("/search", response_model=list[ChatHistorySearchResult])
async def search_history(
    q: str = "",
    mode: str | None = None,
    project_id: UUID | None = None,
    limit: int = 100,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ChatHistorySearchResult]:
    repo = SqlChatRepository(session)
    modes = [mode] if mode in {"general", "mentor", "interviewer"} else ["general", "mentor", "interviewer"]
    needle = _norm(q)
    out: list[ChatHistorySearchResult] = []
    for next_mode in modes:
        for row in await repo.list_sessions(user_id=user.id, mode=next_mode):
            if project_id and _project_id(row) != str(project_id):
                continue
            messages = await repo.list_messages(user_id=user.id, session_id=row.id)
            haystack = _norm(
                " ".join(
                    [
                        row.title or "",
                        row.status,
                        row.mode,
                        _target_text(row.target),
                        " ".join(m.content for m in messages),
                    ]
                )
            )
            if needle and needle not in haystack:
                continue
            message_text = "\n".join(f"{m.role}: {m.content}" for m in messages)
            out.append(
                ChatHistorySearchResult(
                    session=ChatSessionOut(
                        id=row.id,
                        mode=row.mode,
                        title=row.title,
                        project_id=row.project_id,
                        target=row.target,
                        status=row.status,
                        turn_count=row.turn_count,
                        created_at=row.created_at,
                    ),
                    history_mode=next_mode,
                    snippet=_snippet(message_text, q),
                    matched_message_count=sum(1 for m in messages if needle and needle in _norm(m.content)),
                )
            )
            if len(out) >= max(1, min(limit, 200)):
                return out
    return out


def _project_id(row) -> str | None:
    if row.project_id:
        return str(row.project_id)
    target = row.target if isinstance(row.target, dict) else {}
    value = target.get("project_id")
    return str(value) if value else None


def _target_text(target) -> str:
    if not isinstance(target, dict):
        return ""
    return " ".join(str(v) for v in target.values() if isinstance(v, (str, int, float)))


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def _snippet(text: str, query: str) -> str:
    q = query.strip().lower()
    if not text or not q:
        return ""
    lower = text.lower()
    idx = lower.find(q)
    if idx < 0:
        return ""
    start = max(0, idx - 90)
    end = min(len(text), idx + len(q) + 140)
    return ("..." if start else "") + " ".join(text[start:end].split()) + ("..." if end < len(text) else "")
