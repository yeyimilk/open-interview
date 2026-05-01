"""QAMerger: dedup near-duplicates across shards, balance categories, cap totals."""
from __future__ import annotations

import re

from .types import QAItem


def _normalize(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


class QAMerger:
    def __init__(self, *, max_total: int = 25, min_per_category: int = 1) -> None:
        self._max = max_total
        self._min = min_per_category

    def merge(self, item_lists: list[list[QAItem]]) -> list[QAItem]:
        flat: list[QAItem] = []
        for items in item_lists:
            flat.extend(items)
        # Dedup by normalized question text.
        seen: set[str] = set()
        unique: list[QAItem] = []
        for it in flat:
            key = _normalize(it.question)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(it)
        # Group by category, keep at least min_per_category, then fill round-robin.
        by_cat: dict[str, list[QAItem]] = {}
        for it in unique:
            by_cat.setdefault(it.category, []).append(it)
        # Sort each category by difficulty desc to keep the best ones first.
        for cat, lst in by_cat.items():
            lst.sort(key=lambda x: (-x.difficulty, len(x.evidence) == 0))
        result: list[QAItem] = []
        # First pass: min_per_category.
        for cat, lst in by_cat.items():
            for _ in range(min(self._min, len(lst))):
                if not lst:
                    break
                result.append(lst.pop(0))
                if len(result) >= self._max:
                    return result
        # Round-robin remaining slots.
        while len(result) < self._max:
            progress = False
            for cat in list(by_cat.keys()):
                lst = by_cat[cat]
                if not lst:
                    continue
                result.append(lst.pop(0))
                progress = True
                if len(result) >= self._max:
                    break
            if not progress:
                break
        return result
