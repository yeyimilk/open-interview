"""Picker should avoid asking the same resume claim twice in close succession."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from openinterview_core.domain.interviewer.picker import pick_next


@dataclass
class _Item:
    id: UUID
    category: str = "experience_claim"
    difficulty: int = 3
    meta: dict | None = None


def test_picker_skips_recently_asked_claim():
    a = _Item(id=uuid4(), meta={"claim": "Cut p99 latency 40%"})
    b = _Item(id=uuid4(), meta={"claim": "Owned the auth rewrite"})

    # Recent claims contains A's signature -> B should be picked.
    picked = pick_next(
        items=[a, b],
        asked_question_ids=set(),
        long_term=[],
        recent_claims=deque(["cut p99 latency 40%"], maxlen=3),
    )
    assert picked is b


def test_picker_falls_back_to_recent_claim_when_no_alternative():
    a = _Item(id=uuid4(), meta={"claim": "Only claim available"})
    picked = pick_next(
        items=[a],
        asked_question_ids=set(),
        long_term=[],
        recent_claims=deque(["only claim available"], maxlen=3),
    )
    # The penalty doesn't make us return None when there's nothing else.
    assert picked is a


def test_picker_ignores_meta_when_missing():
    # Project-scoped items don't have meta — picker should still work.
    a = _Item(id=uuid4(), category="architecture", difficulty=4)
    b = _Item(id=uuid4(), category="testing", difficulty=2)
    picked = pick_next(
        items=[a, b], asked_question_ids=set(), long_term=[],
    )
    # Higher difficulty wins by the existing scoring.
    assert picked is a
