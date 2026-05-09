"""Interviewer agent: picks a question, takes the user's answer, evaluates it,
optionally probes, then moves on. Uses LangGraph for the per-turn flow.
"""
from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from openinterview_schemas import ChatMessage as ChatMessageDTO
from openinterview_schemas import RetrieveRequest, RetrievalPurpose, RetrievalSource

from ...infra.db.qa_repository import SqlQARepository
from ..memory.recall import RecalledLongTerm
from ..retrieval import RetrievalService
from .picker import _claim_signature, pick_next
from .policy import (
    coerce_thread_state,
    decide_next_action,
    mark_follow_up_asked,
    mark_wrap_up,
    note_answer_for_current_topic,
    start_topic_state,
)


class InterviewerAgent:
    def __init__(
        self,
        *,
        sessionmaker,
        gateway,
        retrieval_service: RetrievalService,
        chat_logical_model: str = "chat-fast",
    ) -> None:
        self._sm = sessionmaker
        self._gw = gateway
        self._retrieval = retrieval_service
        self._model = chat_logical_model

    async def turn(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        qa_set_id: UUID,
        user_input: str,
        asked_ids: set,
        prev_question: str,
        prev_ideal_answer: str,
        recent_claims: list[str] | None = None,
        voice_features: dict | None = None,
        blueprint: dict | None = None,
        thread_state: dict | None = None,
    ) -> dict:
        # Reuse the streaming pipeline and collapse to a single result dict.
        chunks: list[str] = []
        meta: dict = {}
        async for ev in self.stream(
            user_id=user_id,
            session_id=session_id,
            qa_set_id=qa_set_id,
            user_input=user_input,
            asked_ids=asked_ids,
            prev_question=prev_question,
            prev_ideal_answer=prev_ideal_answer,
            recent_claims=recent_claims,
            voice_features=voice_features,
            blueprint=blueprint,
            thread_state=thread_state,
        ):
            t = ev.get("type")
            if t == "token":
                chunks.append(ev.get("content", ""))
            elif t == "done":
                meta = ev.get("meta", {}) or {}
        chosen_id = meta.get("chosen_item_id")
        return {
            "final": "".join(chunks),
            "evaluation": meta.get("evaluation", {}),
            "chosen_item_id": UUID(chosen_id) if chosen_id else None,
            "chosen_question": meta.get("chosen_question", ""),
            "ideal_answer": meta.get("ideal_answer", ""),
            "asked_ids": {UUID(x) for x in meta.get("asked_ids", [])},
            "claim": meta.get("claim"),
            "recent_claims": meta.get("recent_claims", []),
            "next_action": meta.get("next_action"),
            "follow_up_axis": meta.get("follow_up_axis"),
            "thread_state": meta.get("thread_state"),
        }

    async def stream(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        qa_set_id: UUID,
        user_input: str,
        asked_ids: set,
        prev_question: str,
        prev_ideal_answer: str,
        recent_claims: list[str] | None = None,
        voice_features: dict | None = None,
        blueprint: dict | None = None,
        thread_state: dict | None = None,
    ) -> AsyncIterator[dict]:
        """Stream tokens progressively.

        - If there is a previous question, evaluate the answer (non-streamed
          JSON call), then emit the score/feedback header as quickly as possible.
        - Then pick the next question and emit it in small chunks.
        """
        evaluation: dict[str, Any] = {}
        if prev_question and user_input:
            voice_block = ""
            if voice_features:
                # Compact JSON for the prompt — full payload lives on the
                # user message's meta.
                voice_block = (
                    "\nDELIVERY METRICS for the candidate's spoken answer "
                    "(JSON):\n"
                    f"{json.dumps(voice_features, ensure_ascii=False)[:1200]}\n"
                )
            delivery_clause = (
                ', "delivery_score": 1-5, "delivery_feedback": str'
                if voice_features
                else ""
            )
            eval_prompt = (
                "You are evaluating a candidate's answer to an interview question. "
                "Return STRICT JSON: "
                '{"score": 1-5, "feedback": str, "missed_points": [str], '
                '"probe_question": str | null'
                + delivery_clause
                + "}. JSON only.\n"
                + (
                    "When DELIVERY METRICS are present, also score delivery "
                    "(pace, fillers, confidence, language accuracy) and write "
                    "one specific delivery_feedback note (e.g. \"strong opening, "
                    "but ~9 fillers in 90s — slow down\").\n"
                    if voice_features
                    else ""
                )
                + "\n"
                f"QUESTION: {prev_question}\n"
                f"IDEAL ANSWER: {prev_ideal_answer[:1500]}\n"
                f"USER ANSWER: {user_input[:2000]}"
                + voice_block
            )
            try:
                r = await self._gw.chat(
                    user_id=user_id,
                    logical_model=self._model,
                    messages=[ChatMessageDTO(role="user", content=eval_prompt)],
                )
                evaluation = _safe_json(r.content, default={}) or {}
            except Exception:
                evaluation = {}

        # Pick the next seed question candidate, but let the policy decide
        # whether to stay on the current topic first.
        retrieved = await self._retrieval.retrieve(
            RetrieveRequest(
                user_id=user_id,
                session_id=session_id,
                query="interview gaps and strengths",
                purpose=RetrievalPurpose.interviewer,
                sources=[RetrievalSource.long_term_memory],
                top_k=6,
            )
        )
        async with self._sm() as s:
            items = await SqlQARepository(s).list_items(
                user_id=user_id, qa_set_id=qa_set_id
            )
        if blueprint:
            common_items = await self._common_candidates(
                user_id=user_id,
                query=_common_query(
                    user_input=user_input,
                    prev_question=prev_question,
                    blueprint=blueprint,
                ),
                blueprint=blueprint,
            )
            items = list(items) + common_items
        asked = set(asked_ids or set())
        max_seed_topics = int((blueprint or {}).get("n_questions") or 5)
        seed_candidates = [] if len(asked) >= max_seed_topics else list(items)
        recent_dq: deque[str] = deque(
            (recent_claims or []), maxlen=3
        )
        pick = pick_next(
            items=seed_candidates,
            asked_question_ids=asked,
            long_term=_long_term_from_chunks(retrieved.chunks),
            recent_claims=recent_dq,
            category_weights=(blueprint or {}).get("category_weights") if blueprint else None,
        )
        thread = note_answer_for_current_topic(
            coerce_thread_state(thread_state),
            had_answer=bool(prev_question and user_input),
        )
        decision = decide_next_action(
            evaluation=evaluation,
            thread_state=thread,
            has_current_topic=bool(thread.get("current_seed_item_id")),
            has_unasked_seed=pick is not None,
        )

        chunks: list[str] = []

        def _emit(text: str):
            chunks.append(text)
            return {"type": "token", "content": text}

        # 1) Stream evaluation header
        if evaluation:
            score = evaluation.get("score")
            fb = evaluation.get("feedback")
            missed = evaluation.get("missed_points") or []
            if score is not None:
                yield _emit(f"Score: {score}/5\n\n")
            if fb:
                yield _emit(f"Feedback: {fb}\n\n")
            d_score = evaluation.get("delivery_score")
            d_fb = evaluation.get("delivery_feedback")
            if d_score is not None or d_fb:
                bits = []
                if d_score is not None:
                    bits.append(f"{d_score}/5")
                if d_fb:
                    bits.append(str(d_fb))
                yield _emit(f"Delivery: {' — '.join(bits)}\n\n")
            if missed:
                yield _emit("Missed points:\n")
                for m in missed:
                    yield _emit(f"- {m}\n")
                yield _emit("\n")

        # 2) Stream either a depth follow-up or the next seed topic.
        chosen_claim: str | None = None
        chosen_item_id = None
        chosen_q = ""
        ideal = ""
        next_action = decision.action
        follow_up_axis = decision.follow_up_axis

        if decision.action in {"ask_follow_up", "challenge_claim"}:
            generated = await self._generate_thread_question(
                user_id=user_id,
                action=decision.action,
                axis=decision.follow_up_axis,
                thread_state=thread,
                prev_question=prev_question,
                prev_ideal_answer=prev_ideal_answer,
                user_input=user_input,
                evaluation=evaluation,
            )
            if generated is not None:
                chosen_q, ideal = generated
                chosen_item_id = thread.get("current_seed_item_id")
                chosen_claim = (
                    str(thread.get("current_claim"))
                    if thread.get("current_claim")
                    else None
                )
                thread = mark_follow_up_asked(
                    thread,
                    action=decision.action,
                    axis=decision.follow_up_axis,
                )
                yield _emit("Next question:\n")
                step = 24
                for i in range(0, len(chosen_q), step):
                    yield _emit(chosen_q[i : i + step])
            else:
                next_action = "switch_topic" if pick is not None else "wrap_up"
                follow_up_axis = None

        if next_action in {"ask_opener", "switch_topic"} and not chosen_q:
            if pick is None:
                next_action = "wrap_up"
            else:
                asked.add(pick.id)
                chosen_item_id = pick.id
                chosen_q = pick.question
                ideal = pick.ideal_answer

                # Resume-scope: surface the claim so the candidate knows what's
                # being probed. We pull it from the picked item's meta blob.
                pick_meta = getattr(pick, "meta", None)
                if isinstance(pick_meta, dict):
                    if pick_meta.get("source") == "common":
                        source = (
                            pick_meta.get("source_label") or "common interview KB"
                        )
                        yield _emit(f"Source: {source}\n\n")
                    claim_text = (pick_meta.get("claim") or "").strip()
                    section = pick_meta.get("claim_section") or ""
                    if claim_text:
                        chosen_claim = claim_text
                        header = "About this on your resume:\n"
                        header += f"> {claim_text}"
                        if section:
                            header += f"  ({section})"
                        header += "\n\n"
                        yield _emit(header)
                        sig = _claim_signature(pick)
                        if sig:
                            recent_dq.append(sig)

                thread = start_topic_state(
                    pick,
                    action=next_action,
                    claim=chosen_claim,
                    max_topic_answer_count=int(
                        thread.get("max_topic_answer_count") or 3
                    ),
                )
                yield _emit("Next question:\n")
                step = 24
                for i in range(0, len(chosen_q), step):
                    yield _emit(chosen_q[i : i + step])

        if next_action == "wrap_up" and not chosen_q:
            yield _emit(
                "We've covered the planned questions. Use the 'End session' "
                "button to get your full evaluation."
            )
            thread = mark_wrap_up(thread)

        full = "".join(chunks)
        yield {
            "type": "done",
            "content": full,
            "meta": {
                "evaluation": evaluation,
                "chosen_item_id": str(chosen_item_id) if chosen_item_id else None,
                "chosen_question": chosen_q,
                "ideal_answer": ideal,
                "asked_ids": [str(i) for i in asked],
                "claim": chosen_claim,
                "recent_claims": list(recent_dq),
                "next_action": next_action,
                "follow_up_axis": follow_up_axis,
                "thread_state": thread,
            },
        }

    async def _generate_thread_question(
        self,
        *,
        user_id: UUID,
        action: str,
        axis: str | None,
        thread_state: dict,
        prev_question: str,
        prev_ideal_answer: str,
        user_input: str,
        evaluation: dict,
    ) -> tuple[str, str] | None:
        seed_q = str(thread_state.get("current_seed_question") or "")
        seed_a = str(thread_state.get("current_seed_ideal_answer") or "")
        category = str(thread_state.get("current_category") or "general")
        claim = str(thread_state.get("current_claim") or "")
        prompt = (
            "You are a realistic technical interviewer. Generate ONE next "
            "question that stays on the current topic.\n"
            "Return STRICT JSON: {\"question\": str, \"ideal_answer\": str}. "
            "JSON only.\n\n"
            f"ACTION: {action}\n"
            f"FOLLOW_UP_AXIS: {axis or ''}\n"
            f"CATEGORY: {category}\n"
            f"RESUME_CLAIM_OR_TOPIC: {claim}\n"
            f"SEED QUESTION: {seed_q[:1200]}\n"
            f"SEED IDEAL ANSWER: {seed_a[:1200]}\n"
            f"PREVIOUS QUESTION: {prev_question[:1200]}\n"
            f"PREVIOUS IDEAL ANSWER: {prev_ideal_answer[:1200]}\n"
            f"CANDIDATE ANSWER: {user_input[:2000]}\n"
            f"EVALUATION JSON: {json.dumps(evaluation, ensure_ascii=False)[:1200]}\n\n"
            "Rules:\n"
            "- Do not switch topics.\n"
            "- If ACTION is challenge_claim, ask for concrete proof, ownership, "
            "or missing implementation details.\n"
            "- If ACTION is ask_follow_up, probe the FOLLOW_UP_AXIS at a deeper "
            "level than the previous question.\n"
            "- ideal_answer is a short rubric for a strong answer, not a full essay."
        )
        try:
            r = await self._gw.chat(
                user_id=user_id,
                logical_model=self._model,
                messages=[ChatMessageDTO(role="user", content=prompt)],
            )
            data = _safe_json(r.content, default={}) or {}
            question = str(data.get("question") or "").strip()
            ideal = str(data.get("ideal_answer") or "").strip()
            if question:
                return (
                    question,
                    ideal
                    or "A strong answer should give concrete details, trade-offs, and evidence.",
                )
        except Exception:
            return None
        return None

    async def _common_candidates(self, *, user_id: UUID, query: str, blueprint: dict) -> list:
        weights = blueprint.get("category_weights") or {}
        categories = [
            k for k, _ in sorted(weights.items(), key=lambda kv: float(kv[1] or 0), reverse=True)
            if k not in {"experience_claim", "project_overview", "behavioral_grounded"}
        ][:5]
        company = blueprint.get("target_company") if blueprint.get("include_company_style", True) else None
        languages = blueprint.get("languages") or []
        retrieved = await self._retrieval.retrieve(
            RetrieveRequest(
                user_id=user_id,
                query=query,
                purpose=RetrievalPurpose.interviewer,
                sources=[RetrievalSource.common_kb],
                categories=categories or None,
                company=company,
                languages=languages or None,
                top_k=8,
                per_source_top_k={"common_kb": 8},
            )
        )
        out = []
        for m in retrieved.chunks:
            try:
                mid = UUID(m.id)
            except ValueError:
                continue
            q = _question_from_match(m)
            answer = _answer_from_match(m)
            out.append(
                SimpleNamespace(
                    id=mid,
                    category=str(m.metadata.get("category") or "general"),
                    difficulty=3,
                    question=q,
                    ideal_answer=answer,
                    follow_up_axes=[],
                    meta={
                        "source": "common",
                        "source_label": m.metadata.get("source") or "common",
                        "company": m.metadata.get("company"),
                        "language": m.metadata.get("language"),
                        "tags": m.metadata.get("tags") or [],
                    },
                )
            )
        return out


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


def _common_query(*, user_input: str, prev_question: str, blueprint: dict) -> str:
    bits = [
        user_input,
        prev_question,
        blueprint.get("target_company") or "",
        " ".join(blueprint.get("languages") or []),
        " ".join((blueprint.get("category_weights") or {}).keys()),
    ]
    return " ".join(x for x in bits if x).strip() or "realistic software engineering mock interview question"


def _question_from_match(match) -> str:
    text = (match.text or "").strip()
    for line in text.splitlines():
        s = line.strip()
        if s.endswith("?"):
            return s[:800]
    if match.title.endswith("?"):
        return match.title
    return f"Walk me through this interview topic: {match.title}"


def _answer_from_match(match) -> str:
    text = (match.text or "").strip()
    if text:
        return text[:1500]
    return "A strong answer should cover the approach, trade-offs, edge cases, and level-appropriate depth."


def _long_term_from_chunks(chunks) -> list[RecalledLongTerm]:
    out: list[RecalledLongTerm] = []
    for c in chunks:
        if c.source != RetrievalSource.long_term_memory:
            continue
        out.append(
            RecalledLongTerm(
                id=c.id,
                kind=str(c.metadata.get("kind") or c.title or "fact"),
                content=c.text,
                score=c.score,
            )
        )
    return out
