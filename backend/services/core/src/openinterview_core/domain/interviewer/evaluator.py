"""SessionEvaluator: at session end, scores the entire transcript and produces
a rubric, strengths, weaknesses, and suggested practice."""
from __future__ import annotations

import json
from uuid import UUID

from openinterview_schemas import ChatMessage as ChatMessageDTO

from ...infra.db.chat_repository import SqlChatRepository
from ..memory.recall import MemoryRetriever


class SessionEvaluator:
    def __init__(
        self,
        *,
        sessionmaker,
        gateway,
        retriever: MemoryRetriever,
        logical_model: str = "chat-strong",
    ) -> None:
        self._sm = sessionmaker
        self._gw = gateway
        self._retriever = retriever
        self._model = logical_model

    async def evaluate(
        self, *, user_id: UUID, session_id: UUID
    ) -> dict:
        async with self._sm() as s:
            msgs = await SqlChatRepository(s).list_messages(
                user_id=user_id, session_id=session_id
            )
        transcript = "\n".join(f"{m.role.upper()}: {m.content}" for m in msgs)
        prompt = (
            "You are an interview panel chair. Read the mock interview transcript and "
            "produce STRICT JSON:\n"
            '{"overall_score": 0.0-5.0, "scores": {"<category>": 0.0-5.0}, '
            '"summary": str, "strengths": [str], "weaknesses": [str], '
            '"suggested_practice": [{"area": str, "why": str, "next_step": str}]}\n'
            "Use these categories where applicable: architecture, code_quality, "
            "data_modeling, scaling, testing, applied_ai_specific, behavioral_grounded.\n"
            "JSON only.\n\n"
            f"TRANSCRIPT:\n{transcript[:12000]}"
        )
        try:
            r = await self._gw.chat(
                user_id=user_id,
                logical_model=self._model,
                messages=[ChatMessageDTO(role="user", content=prompt)],
            )
            data = _safe_json(r.content, default={}) or {}
        except Exception:
            data = {}

        overall = float(data.get("overall_score") or 0.0)
        scores = data.get("scores") or {}
        summary = str(data.get("summary") or "")
        strengths = list(data.get("strengths") or [])
        weaknesses = list(data.get("weaknesses") or [])
        suggested = list(data.get("suggested_practice") or [])

        # Persist evaluation row.
        async with self._sm() as s:
            await SqlChatRepository(s).save_evaluation(
                session_id=session_id,
                user_id=user_id,
                overall_score=overall,
                scores={k: float(v) for k, v in scores.items() if isinstance(v, (int, float))},
                summary=summary,
                strengths=strengths,
                weaknesses=weaknesses,
                suggested_practice=suggested,
            )

        # Push gaps + strengths to long-term memory.
        items: list[tuple[str, str, float]] = []
        for w in weaknesses[:5]:
            if isinstance(w, str) and w.strip():
                items.append(("gap", w.strip(), 0.8))
        for s_ in strengths[:5]:
            if isinstance(s_, str) and s_.strip():
                items.append(("strength", s_.strip(), 0.8))
        if items:
            await self._retriever.store_long_term(
                user_id=user_id, items=items, source_session_id=session_id
            )

        return {
            "overall_score": overall,
            "scores": scores,
            "summary": summary,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "suggested_practice": suggested,
        }


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
