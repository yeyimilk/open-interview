"""Question picker: select the next QA item for an interviewer session.

Strategy:
- Pull QA items for the project at the requested level.
- Deprioritize categories the user is already strong in (long-term memory).
- Prioritize categories the user has gaps in.
- Avoid repeats within the same session.
"""
from __future__ import annotations

from collections import Counter
from uuid import UUID

from ..memory.recall import RecalledLongTerm


def pick_next(
    *,
    items: list,
    asked_question_ids: set[UUID],
    long_term: list[RecalledLongTerm],
):
    if not items:
        return None
    # Priority: gap categories first, strength categories last.
    gap_terms = " ".join(lt.content.lower() for lt in long_term if lt.kind == "gap")
    strength_terms = " ".join(lt.content.lower() for lt in long_term if lt.kind == "strength")

    def score(item) -> float:
        s = 0.0
        cat = (item.category or "").lower()
        if cat and cat in gap_terms:
            s += 2.0
        if cat and cat in strength_terms:
            s -= 1.0
        # Prefer mid-difficulty for variety.
        s += 0.1 * (3 - abs(3 - item.difficulty))
        # Heavily penalize already-asked.
        if item.id in asked_question_ids:
            s -= 100.0
        return s

    sorted_items = sorted(items, key=score, reverse=True)
    return sorted_items[0] if sorted_items[0].id not in asked_question_ids else None
