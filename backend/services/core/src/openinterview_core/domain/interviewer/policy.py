from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..qa.types import CANONICAL_FOLLOW_UP_AXES, normalize_follow_up_axes

InterviewAction = Literal[
    "ask_opener",
    "ask_follow_up",
    "challenge_claim",
    "switch_topic",
    "wrap_up",
]

DEFAULT_MAX_TOPIC_ANSWERS = 3


@dataclass(frozen=True)
class InterviewPolicyDecision:
    action: InterviewAction
    follow_up_axis: str | None = None


def coerce_thread_state(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    return {
        "current_seed_item_id": raw.get("current_seed_item_id"),
        "current_seed_question": str(raw.get("current_seed_question") or ""),
        "current_seed_ideal_answer": str(raw.get("current_seed_ideal_answer") or ""),
        "current_category": str(raw.get("current_category") or ""),
        "current_claim": raw.get("current_claim"),
        "topic_answer_count": max(0, _to_int(raw.get("topic_answer_count"), 0)),
        "max_topic_answer_count": max(
            1,
            _to_int(
                raw.get("max_topic_answer_count"), DEFAULT_MAX_TOPIC_ANSWERS
            ),
        ),
        "used_axes": _clean_axis_list(raw.get("used_axes")),
        "remaining_axes": _clean_axis_list(raw.get("remaining_axes")),
        "last_action": raw.get("last_action"),
        "last_axis": raw.get("last_axis"),
    }


def start_topic_state(
    item,
    *,
    action: InterviewAction,
    claim: str | None = None,
    max_topic_answer_count: int = DEFAULT_MAX_TOPIC_ANSWERS,
) -> dict:
    axes = normalize_follow_up_axes(
        getattr(item, "follow_up_axes", None), category=getattr(item, "category", None)
    )
    return {
        "current_seed_item_id": str(item.id),
        "current_seed_question": str(item.question or ""),
        "current_seed_ideal_answer": str(item.ideal_answer or ""),
        "current_category": str(item.category or ""),
        "current_claim": claim,
        "topic_answer_count": 0,
        "max_topic_answer_count": max(1, int(max_topic_answer_count or 1)),
        "used_axes": [],
        "remaining_axes": axes,
        "last_action": action,
        "last_axis": None,
    }


def note_answer_for_current_topic(state: dict, *, had_answer: bool) -> dict:
    state = coerce_thread_state(state)
    if had_answer and state.get("current_seed_item_id"):
        state["topic_answer_count"] = int(state.get("topic_answer_count") or 0) + 1
    return state


def decide_next_action(
    *,
    evaluation: dict,
    thread_state: dict,
    has_current_topic: bool,
    has_unasked_seed: bool,
) -> InterviewPolicyDecision:
    state = coerce_thread_state(thread_state)
    if not has_current_topic:
        if has_unasked_seed:
            return InterviewPolicyDecision("ask_opener")
        return InterviewPolicyDecision("wrap_up")

    topic_answers = int(state.get("topic_answer_count") or 0)
    max_answers = int(state.get("max_topic_answer_count") or DEFAULT_MAX_TOPIC_ANSWERS)
    if topic_answers >= max_answers:
        return InterviewPolicyDecision(
            "switch_topic" if has_unasked_seed else "wrap_up"
        )

    remaining = _clean_axis_list(state.get("remaining_axes"))
    score = _score(evaluation)
    if score is not None and score <= 2 and topic_answers <= 1:
        axis = remaining[0] if remaining else "implementation_details"
        return InterviewPolicyDecision("challenge_claim", axis)

    if remaining:
        return InterviewPolicyDecision("ask_follow_up", remaining[0])

    return InterviewPolicyDecision("switch_topic" if has_unasked_seed else "wrap_up")


def mark_follow_up_asked(
    state: dict, *, action: InterviewAction, axis: str | None
) -> dict:
    state = coerce_thread_state(state)
    remaining = _clean_axis_list(state.get("remaining_axes"))
    used = _clean_axis_list(state.get("used_axes"))
    if axis:
        if axis in remaining:
            remaining.remove(axis)
        if axis not in used:
            used.append(axis)
    state["remaining_axes"] = remaining
    state["used_axes"] = used
    state["last_action"] = action
    state["last_axis"] = axis
    return state


def mark_wrap_up(state: dict) -> dict:
    state = coerce_thread_state(state)
    state["last_action"] = "wrap_up"
    state["last_axis"] = None
    return state


def _score(evaluation: dict) -> float | None:
    try:
        raw = evaluation.get("score")
        if raw is None:
            return None
        return float(raw)
    except (AttributeError, TypeError, ValueError):
        return None


def _clean_axis_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    canonical = set(CANONICAL_FOLLOW_UP_AXES)
    for v in raw:
        if not isinstance(v, str):
            continue
        key = v.strip().lower()
        if key in canonical and key not in out:
            out.append(key)
    return out


def _to_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
