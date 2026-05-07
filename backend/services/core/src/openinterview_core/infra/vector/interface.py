"""Vector store interface. Concrete adapters: Chroma, in-memory (tests)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class VectorRecord:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorMatch:
    id: str
    text: str
    metadata: dict[str, Any]
    score: float


class VectorStore(Protocol):
    async def upsert(
        self, *, collection: str, records: list[VectorRecord], embeddings: list[list[float]]
    ) -> None: ...

    async def query(
        self,
        *,
        collection: str,
        embedding: list[float],
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[VectorMatch]: ...

    async def delete(self, *, collection: str, ids: list[str]) -> None: ...

    async def delete_collection(self, collection: str) -> None: ...
