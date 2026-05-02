"""Interviewer agent: picks a question, takes the user's answer, evaluates it,
optionally probes, then moves on. Uses LangGraph for the per-turn flow.
"""
from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from openinterview_schemas import ChatMessage as ChatMessageDTO

from ...infra.db.qa_repository import SqlQARepository
from ...infra.db.chat_repository import SqlChatRepository
from ..memory.recall import MemoryRetriever
from .picker import _claim_signature, pick_next


class _State(TypedDict, total=False):
    user_id: UUID
    session_id: UUID
    qa_set_id: UUID
    user_input: str
    asked_ids: set
    chosen_item_id: UUID
    chosen_question: str
    ideal_answer: str
    evaluation: dict
    final: str


class InterviewerAgent:
    def __init__(
        self,
        *,
        sessionmaker,
        gateway,
        retriever: MemoryRetriever,
        chat_logical_model: str = "chat-fast",
    ) -> None:
        self._sm = sessionmaker
        self._gw = gateway
        self._retriever = retriever
        self._model = chat_logical_model
        self._graph = self._build_graph()

    def _build_graph(self):
        g = StateGraph(_State)

        async def evaluate_and_next(state: _State) -> dict:
            # 1) If we have a previous question, evaluate the user's answer.
            evaluation: dict[str, Any] = {}
            if state.get("chosen_question") and state.get("user_input"):
                eval_prompt = (
                    "You are evaluating a candidate's answer to an interview question. "
                    "Return STRICT JSON: "
                    '{"score": 1-5, "feedback": str, "missed_points": [str], '
                    '"probe_question": str | null}. JSON only.\n\n'
                    f"QUESTION: {state['chosen_question']}\n"
                    f"IDEAL ANSWER: {state.get('ideal_answer','')[:1500]}\n"
                    f"USER ANSWER: {state['user_input'][:2000]}"
                )
                try:
                    r = await self._gw.chat(
                        user_id=state["user_id"],
                        logical_model=self._model,
                        messages=[ChatMessageDTO(role="user", content=eval_prompt)],
                    )
                    evaluation = _safe_json(r.content, default={}) or {}
                except Exception:
                    evaluation = {}

            # 2) Pick the next question.
            recalled = await self._retriever.recall(
                user_id=state["user_id"],
                session_id=state.get("session_id"),
                query="interview gaps and strengths",
            )
            async with self._sm() as s:
                items = await SqlQARepository(s).list_items(
                    user_id=state["user_id"], qa_set_id=state["qa_set_id"]
                )
            asked = state.get("asked_ids") or set()
            pick = pick_next(
                items=items,
                asked_question_ids=asked,
                long_term=recalled.long_term,
            )

            if pick is None:
                # No more questions: ask the user to wrap up.
                final = self._format_response(
                    evaluation=evaluation,
                    next_question=None,
                    ideal_answer=None,
                )
                return {
                    "evaluation": evaluation,
                    "chosen_item_id": None,
                    "chosen_question": "",
                    "ideal_answer": "",
                    "final": final,
                }

            asked.add(pick.id)
            final = self._format_response(
                evaluation=evaluation,
                next_question=pick.question,
                ideal_answer=None,
            )
            return {
                "evaluation": evaluation,
                "chosen_item_id": pick.id,
                "chosen_question": pick.question,
                "ideal_answer": pick.ideal_answer,
                "asked_ids": asked,
                "final": final,
            }

        g.add_node("eval_next", evaluate_and_next)
        g.add_edge(START, "eval_next")
        g.add_edge("eval_next", END)
        return g.compile()

    def _format_response(
        self,
        *,
        evaluation: dict,
        next_question: str | None,
        ideal_answer: str | None,
    ) -> str:
        parts: list[str] = []
        if evaluation:
            score = evaluation.get("score")
            fb = evaluation.get("feedback")
            missed = evaluation.get("missed_points") or []
            if score is not None:
                parts.append(f"Score: {score}/5")
            if fb:
                parts.append(f"Feedback: {fb}")
            if missed:
                parts.append("Missed points:\n- " + "\n- ".join(str(m) for m in missed))
            probe = evaluation.get("probe_question")
            if probe and not next_question:
                parts.append(f"Quick follow-up: {probe}")
        if next_question:
            parts.append(f"\nNext question:\n{next_question}")
        else:
            parts.append("\nWe've covered the planned questions. Use the 'End session' button to get your full evaluation.")
        return "\n\n".join(parts).strip()

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
    ) -> AsyncIterator[dict]:
        """Stream tokens progressively.

        - If there is a previous question, evaluate the answer (non-streamed
          JSON call), then emit the score/feedback header as quickly as possible.
        - Then pick the next question and emit it in small chunks.
        """
        evaluation: dict[str, Any] = {}
        if prev_question and user_input:
            eval_prompt = (
                "You are evaluating a candidate's answer to an interview question. "
                "Return STRICT JSON: "
                '{"score": 1-5, "feedback": str, "missed_points": [str], '
                '"probe_question": str | null}. JSON only.\n\n'
                f"QUESTION: {prev_question}\n"
                f"IDEAL ANSWER: {prev_ideal_answer[:1500]}\n"
                f"USER ANSWER: {user_input[:2000]}"
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

        # Pick next question (local)
        recalled = await self._retriever.recall(
            user_id=user_id,
            session_id=session_id,
            query="interview gaps and strengths",
        )
        async with self._sm() as s:
            items = await SqlQARepository(s).list_items(
                user_id=user_id, qa_set_id=qa_set_id
            )
        asked = set(asked_ids or set())
        recent_dq: deque[str] = deque(
            (recent_claims or []), maxlen=3
        )
        pick = pick_next(
            items=items,
            asked_question_ids=asked,
            long_term=recalled.long_term,
            recent_claims=recent_dq,
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
            if missed:
                yield _emit("Missed points:\n")
                for m in missed:
                    yield _emit(f"- {m}\n")
                yield _emit("\n")
            probe = evaluation.get("probe_question")
            if probe and pick is None:
                yield _emit(f"Quick follow-up: {probe}\n\n")

        # 2) Stream next question (chunked for UI typing effect)
        chosen_claim: str | None = None
        if pick is None:
            yield _emit(
                "We've covered the planned questions. Use the 'End session' "
                "button to get your full evaluation."
            )
            chosen_item_id = None
            chosen_q = ""
            ideal = ""
        else:
            asked.add(pick.id)
            chosen_item_id = pick.id
            chosen_q = pick.question
            ideal = pick.ideal_answer

            # Resume-scope: surface the claim so the candidate knows what's
            # being probed. We pull it from the picked item's meta blob.
            pick_meta = getattr(pick, "meta", None)
            if isinstance(pick_meta, dict):
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

            yield _emit("Next question:\n")
            # Smaller chunks (~24 chars) make the UI feel like typing.
            q = pick.question
            step = 24
            for i in range(0, len(q), step):
                yield _emit(q[i : i + step])

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
            },
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
