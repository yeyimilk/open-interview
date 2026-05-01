"""In-memory vector store for tests and offline dev."""
from __future__ import annotations

import math
from typing import Any

from .interface import VectorMatch, VectorRecord, VectorStore


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self._cols: dict[str, list[tuple[VectorRecord, list[float]]]] = {}

    async def upsert(self, *, collection, records, embeddings) -> None:  # type: ignore[override]
        bucket = self._cols.setdefault(collection, [])
        existing = {rec.id: i for i, (rec, _) in enumerate(bucket)}
        for rec, emb in zip(records, embeddings, strict=True):
            if rec.id in existing:
                bucket[existing[rec.id]] = (rec, emb)
            else:
                bucket.append((rec, emb))

    async def query(self, *, collection, embedding, k, where=None) -> list[VectorMatch]:  # type: ignore[override]
        bucket = self._cols.get(collection, [])
        scored = []
        for rec, emb in bucket:
            if where and not _matches(rec.metadata, where):
                continue
            scored.append(
                VectorMatch(id=rec.id, text=rec.text, metadata=dict(rec.metadata), score=_cos(embedding, emb))
            )
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:k]

    async def delete_collection(self, collection: str) -> None:  # type: ignore[override]
        self._cols.pop(collection, None)


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n]))
    nb = math.sqrt(sum(x * x for x in b[:n]))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _matches(meta: dict[str, Any], where: dict[str, Any]) -> bool:
    return all(meta.get(k) == v for k, v in where.items())
