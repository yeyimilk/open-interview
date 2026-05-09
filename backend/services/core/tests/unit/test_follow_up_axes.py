from __future__ import annotations

from openinterview_core.domain.qa.merger import QAMerger
from openinterview_core.domain.qa.types import QAItem, normalize_follow_up_axes


def test_normalize_follow_up_axes_accepts_aliases_and_caps():
    axes = normalize_follow_up_axes(
        [
            "implementation details",
            "trade-offs",
            "scaling",
            "debug",
            "ownership",
            "metrics",
        ],
        category="architecture",
    )

    assert axes == [
        "implementation_details",
        "trade_offs",
        "scale",
        "debugging",
        "ownership",
    ]


def test_normalize_follow_up_axes_defaults_by_category():
    assert normalize_follow_up_axes([], category="behavioral_grounded") == [
        "ownership",
        "reflection",
        "trade_offs",
        "failure_modes",
        "metrics",
    ]


def test_merger_preserves_follow_up_axes():
    item = QAItem(
        category="architecture",
        level="mid",
        question="How is the API split?",
        ideal_answer="Discuss handlers and services.",
        difficulty=4,
        follow_up_axes=["trade_offs", "scale"],
    )

    merged = QAMerger(max_total=3).merge([[item]])

    assert merged[0].follow_up_axes == ["trade_offs", "scale"]
