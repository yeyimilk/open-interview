"""Chroma adapter (HTTP). Uses chromadb client when available; otherwise fails loudly.

Imported lazily so tests using the in-memory backend don't need chromadb installed.
"""
from __future__ import annotations

from typing import Any

from .interface import VectorMatch, VectorRecord, VectorStore


class ChromaVectorStore(VectorStore):
    def __init__(self, url: str) -> None:
        try:
            import chromadb  # type: ignore
        except ImportError as e:  # pragma: no cover - optional dep
            raise RuntimeError(
                "chromadb is required for VECTOR_BACKEND=chroma. pip install chromadb."
            ) from e
        from urllib.parse import urlparse

        u = urlparse(url)
        host = u.hostname or "localhost"
        port = u.port or 8000
        self._client = chromadb.HttpClient(host=host, port=port)

    def _coll(self, name: str):
        return self._client.get_or_create_collection(name=name)

    async def upsert(self, *, collection, records, embeddings) -> None:  # type: ignore[override]
        c = self._coll(collection)
        c.upsert(
            ids=[r.id for r in records],
            documents=[r.text for r in records],
            metadatas=[r.metadata for r in records],
            embeddings=embeddings,
        )

    async def query(self, *, collection, embedding, k, where=None) -> list[VectorMatch]:  # type: ignore[override]
        c = self._coll(collection)
        res = c.query(query_embeddings=[embedding], n_results=k, where=where or None)
        out: list[VectorMatch] = []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for i in range(len(ids)):
            score = 1.0 - float(dists[i]) if i < len(dists) else 0.0
            out.append(VectorMatch(id=ids[i], text=docs[i], metadata=dict(metas[i] or {}), score=score))
        return out

    async def delete_collection(self, collection: str) -> None:  # type: ignore[override]
        try:
            self._client.delete_collection(collection)
        except Exception:  # pragma: no cover
            pass


def vector_collection_for_user_project(user_id: str, project_id: str) -> str:
    return f"user_{user_id}_project_{project_id}".replace("-", "")


def vector_collection_for_user_qa(user_id: str) -> str:
    return f"user_{user_id}_qa".replace("-", "")


def vector_collection_for_user_memory(user_id: str) -> str:
    return f"user_{user_id}_memory".replace("-", "")
