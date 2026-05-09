from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from openinterview_core.domain.interviewer.policy import (
    decide_next_action,
    mark_follow_up_asked,
    note_answer_for_current_topic,
    start_topic_state,
)


def _item():
    return SimpleNamespace(
        id=uuid4(),
        category="architecture",
        question="Describe the architecture.",
        ideal_answer="Clear boundaries and trade-offs.",
        follow_up_axes=["implementation_details", "trade_offs"],
    )


def test_policy_starts_with_opener_when_no_current_topic():
    d = decide_next_action(
        evaluation={},
        thread_state={},
        has_current_topic=False,
        has_unasked_seed=True,
    )

    assert d.action == "ask_opener"


def test_policy_follow_up_for_strong_answer_with_remaining_axes():
    state = start_topic_state(_item(), action="ask_opener")
    state = note_answer_for_current_topic(state, had_answer=True)

    d = decide_next_action(
        evaluation={"score": 4},
        thread_state=state,
        has_current_topic=True,
        has_unasked_seed=True,
    )

    assert d.action == "ask_follow_up"
    assert d.follow_up_axis == "implementation_details"


def test_policy_challenges_shallow_first_answer():
    state = start_topic_state(_item(), action="ask_opener")
    state = note_answer_for_current_topic(state, had_answer=True)

    d = decide_next_action(
        evaluation={"score": 2},
        thread_state=state,
        has_current_topic=True,
        has_unasked_seed=True,
    )

    assert d.action == "challenge_claim"
    assert d.follow_up_axis == "implementation_details"


def test_policy_switches_after_depth_budget():
    state = start_topic_state(_item(), action="ask_opener")
    state["topic_answer_count"] = state["max_topic_answer_count"]

    d = decide_next_action(
        evaluation={"score": 4},
        thread_state=state,
        has_current_topic=True,
        has_unasked_seed=True,
    )

    assert d.action == "switch_topic"


def test_mark_follow_up_asked_consumes_axis():
    state = start_topic_state(_item(), action="ask_opener")

    updated = mark_follow_up_asked(
        state,
        action="ask_follow_up",
        axis="implementation_details",
    )

    assert updated["used_axes"] == ["implementation_details"]
    assert updated["remaining_axes"] == ["trade_offs"]
    assert updated["last_action"] == "ask_follow_up"
