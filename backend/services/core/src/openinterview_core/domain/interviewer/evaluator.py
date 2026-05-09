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
        coverage = _coverage_events(msgs)
        coverage_block = (
            "\n\nINTERVIEW COVERAGE EVENTS:\n"
            f"{json.dumps(coverage, ensure_ascii=False)[:2000]}"
            if coverage
            else ""
        )

        # Aggregate per-turn voice analysis (audio-mode interviews only).
        delivery_summary = _aggregate_voice([
            (m.meta or {}).get("voice")
            for m in msgs
            if m.role == "user" and isinstance(m.meta, dict)
        ])
        has_delivery = delivery_summary is not None

        delivery_block = ""
        delivery_clause = ""
        if has_delivery:
            delivery_block = (
                "\n\nDELIVERY METRICS (aggregated across all spoken answers):\n"
                f"{json.dumps(delivery_summary, ensure_ascii=False)[:1500]}"
            )
            delivery_clause = (
                ', "delivery_score": 0.0-5.0, '
                '"delivery_feedback": [{"area": str, "note": str}]'
            )

        prompt = (
            "You are an interview panel chair. Read the mock interview transcript and "
            "produce STRICT JSON:\n"
            '{"overall_score": 0.0-5.0, "scores": {"<category>": 0.0-5.0}, '
            '"summary": str, "strengths": [str], "weaknesses": [str], '
            '"suggested_practice": [{"area": str, "why": str, "next_step": str}]'
            + delivery_clause
            + "}\n"
            "Use these categories where applicable: architecture, code_quality, "
            "data_modeling, scaling, testing, applied_ai_specific, behavioral_grounded.\n"
            "When INTERVIEW COVERAGE EVENTS are present, use them to comment on "
            "both breadth across seed topics and depth through follow-ups.\n"
            + (
                "When DELIVERY METRICS are present, produce delivery_score "
                "(speaking pace, fillers, confidence, language accuracy) and a "
                "list of concise delivery_feedback notes.\n"
                if has_delivery
                else ""
            )
            + "JSON only.\n\n"
            f"TRANSCRIPT:\n{transcript[:12000]}"
            + coverage_block
            + delivery_block
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

        # Delivery rubric — only persist when the session was audio-mode.
        delivery_score: float | None = None
        delivery_feedback: list = []
        delivery_summary_out: dict | None = None
        if has_delivery:
            try:
                delivery_score = float(data.get("delivery_score") or 0.0)
            except (TypeError, ValueError):
                delivery_score = None
            df = data.get("delivery_feedback") or []
            if isinstance(df, list):
                delivery_feedback = df
            delivery_summary_out = {
                "metrics": delivery_summary,
                "feedback": delivery_feedback,
            }

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
                delivery_score=delivery_score,
                delivery_summary=delivery_summary_out,
            )

        # Push gaps + strengths to long-term memory.
        items: list[tuple[str, str, float]] = []
        for w in weaknesses[:5]:
            if isinstance(w, str) and w.strip():
                items.append(("gap", w.strip(), 0.8))
        for s_ in strengths[:5]:
            if isinstance(s_, str) and s_.strip():
                items.append(("strength", s_.strip(), 0.8))
        for note in delivery_feedback[:5]:
            text = ""
            if isinstance(note, dict):
                text = str(note.get("note") or note.get("area") or "").strip()
            elif isinstance(note, str):
                text = note.strip()
            if text:
                items.append(("delivery_gap", text, 0.7))
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
            "delivery_score": delivery_score,
            "delivery_summary": delivery_summary_out,
        }


def _aggregate_voice(voice_blobs: list[dict | None]) -> dict | None:
    """Roll up per-turn voice analyses into a session-level summary.

    Returns None when there is no audio data (text-only session)."""
    blobs = [v for v in voice_blobs if isinstance(v, dict)]
    if not blobs:
        return None

    def _avg(key: str) -> float | None:
        vals: list[float] = []
        for b in blobs:
            x = b.get(key)
            if isinstance(x, (int, float)):
                vals.append(float(x))
        return round(sum(vals) / len(vals), 2) if vals else None

    def _avg_tone(key: str) -> float | None:
        vals: list[float] = []
        for b in blobs:
            t = b.get("tone") or {}
            x = t.get(key) if isinstance(t, dict) else None
            if isinstance(x, (int, float)):
                vals.append(float(x))
        return round(sum(vals) / len(vals), 2) if vals else None

    fillers: dict[str, int] = {}
    total_pause = 0
    total_long_pauses = 0
    total_duration = 0.0
    lang_issues: list[str] = []
    pron_issues: list[dict] = []
    for b in blobs:
        for fw in b.get("filler_words") or []:
            if isinstance(fw, dict):
                w = str(fw.get("word") or "").strip().lower()
                c = fw.get("count") or 0
                if w and isinstance(c, (int, float)):
                    fillers[w] = fillers.get(w, 0) + int(c)
        if isinstance(b.get("pause_count"), (int, float)):
            total_pause += int(b["pause_count"])
        lp = b.get("long_pauses_s") or []
        if isinstance(lp, list):
            total_long_pauses += len(lp)
        if isinstance(b.get("duration_s"), (int, float)):
            total_duration += float(b["duration_s"])
        la = b.get("language_accuracy") or {}
        for issue in (la.get("issues") or []) if isinstance(la, dict) else []:
            if isinstance(issue, str) and issue.strip():
                lang_issues.append(issue.strip())
        for p in b.get("pronunciation_issues") or []:
            if isinstance(p, dict) and p.get("word"):
                pron_issues.append(
                    {"word": str(p["word"]), "note": str(p.get("note") or "")}
                )

    return {
        "turn_count": len(blobs),
        "total_duration_s": round(total_duration, 2),
        "avg_wpm": _avg("wpm"),
        "filler_counts": [
            {"word": w, "count": c}
            for w, c in sorted(fillers.items(), key=lambda kv: -kv[1])[:8]
        ],
        "total_pause_count": total_pause,
        "total_long_pauses": total_long_pauses,
        "avg_tone": {
            "confidence": _avg_tone("confidence"),
            "energy": _avg_tone("energy"),
            "monotone": _avg_tone("monotone"),
        },
        "avg_language_accuracy": _avg_language(blobs),
        "language_issues": lang_issues[:10],
        "pronunciation_issues": pron_issues[:10],
    }


def _coverage_events(messages) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m.role != "assistant" or not isinstance(m.meta, dict):
            continue
        action = m.meta.get("next_action")
        if not action:
            continue
        state = m.meta.get("thread_state") or {}
        out.append(
            {
                "action": action,
                "axis": m.meta.get("follow_up_axis"),
                "category": (
                    state.get("current_category") if isinstance(state, dict) else None
                ),
                "topic_answer_count": (
                    state.get("topic_answer_count") if isinstance(state, dict) else None
                ),
            }
        )
    return out[-20:]


def _avg_language(blobs: list[dict]) -> float | None:
    vals: list[float] = []
    for b in blobs:
        la = b.get("language_accuracy") or {}
        if isinstance(la, dict):
            s = la.get("score")
            if isinstance(s, (int, float)):
                vals.append(float(s))
    return round(sum(vals) / len(vals), 2) if vals else None


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
