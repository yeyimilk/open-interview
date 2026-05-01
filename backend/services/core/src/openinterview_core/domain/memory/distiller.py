"""Memory distiller: turns a finished session into:
- one episodic summary (per-session)
- a small set of long-term entries (strengths, gaps, preferences, facts)
"""
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_schemas import ChatMessage as ChatMessageDTO

from ...infra.db.chat_repository import SqlChatRepository
from ...infra.db.memory_repository import SqlMemoryRepository
from .recall import MemoryRetriever


class MemoryDistiller:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        gateway,
        retriever: MemoryRetriever,
        logical_model: str = "chat-strong",
    ) -> None:
        self._sm = sessionmaker
        self._gw = gateway
        self._retriever = retriever
        self._model = logical_model

    async def distill(self, *, user_id: UUID, session_id: UUID) -> None:
        async with self._sm() as s:
            msgs = await SqlChatRepository(s).list_messages(
                user_id=user_id, session_id=session_id
            )
        if not msgs:
            return
        transcript = "\n".join(f"{m.role.upper()}: {m.content}" for m in msgs)
        prompt = (
            "You are distilling a coaching/interview session into durable memory.\n"
            "Read the transcript and produce STRICT JSON:\n"
            '{"episodic_summary": str, "entities": {"projects":[str], "topics":[str]},'
            ' "long_term": [{"kind": "strength|gap|preference|fact", "content": str, "weight": 0.1-1.0}]}\n'
            "Rules:\n"
            "- 3-6 long-term items max. Skip noise.\n"
            "- 'gap' items must be specific ('shaky on async cancellation in asyncio'), not vague.\n"
            "- weight: 1.0=very confident, 0.5=tentative.\n"
            "- JSON only, no prose.\n\n"
            f"TRANSCRIPT:\n{transcript[:8000]}"
        )
        try:
            r = await self._gw.chat(
                user_id=user_id,
                logical_model=self._model,
                messages=[ChatMessageDTO(role="user", content=prompt)],
            )
            data = _safe_json(r.content, default={})
        except Exception:
            return

        ep_summary = str(data.get("episodic_summary") or "").strip()
        entities = data.get("entities") if isinstance(data.get("entities"), dict) else {}
        long_term = data.get("long_term") or []

        if ep_summary:
            async with self._sm() as s:
                await SqlMemoryRepository(s).add_episodic(
                    user_id=user_id,
                    session_id=session_id,
                    summary=ep_summary,
                    entities=entities,
                )

        items: list[tuple[str, str, float]] = []
        for it in long_term:
            if not isinstance(it, dict):
                continue
            kind = str(it.get("kind") or "fact")
            if kind not in ("strength", "gap", "preference", "fact"):
                kind = "fact"
            content = str(it.get("content") or "").strip()
            if not content:
                continue
            try:
                weight = float(it.get("weight") or 0.7)
            except Exception:
                weight = 0.7
            weight = max(0.1, min(1.0, weight))
            items.append((kind, content, weight))

        if items:
            await self._retriever.store_long_term(
                user_id=user_id,
                items=items,
                source_session_id=session_id,
            )


def _safe_json(text: str, *, default):
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        return json.loads(cleaned)
    except Exception:
        return default
