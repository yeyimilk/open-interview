"""Memory retrieval: combine working (recent messages), episodic (summaries),
and long-term (durable facts/strengths/gaps) into a single context bundle."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...infra.db.chat_repository import SqlChatRepository
from ...infra.db.memory_repository import SqlMemoryRepository
from ...infra.vector import (
    VectorRecord,
    VectorStore,
    vector_collection_for_user_memory,
)


@dataclass
class RecalledLongTerm:
    id: str
    kind: str
    content: str
    score: float = 0.0


@dataclass
class RecallResult:
    working_messages: list[dict] = field(default_factory=list)  # [{role, content}]
    episodic_summaries: list[str] = field(default_factory=list)
    long_term: list[RecalledLongTerm] = field(default_factory=list)


class MemoryRetriever:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        gateway,
        embedder,
        vector_store: VectorStore,
        working_window: int = 12,
        episodic_limit: int = 5,
        long_term_k: int = 6,
    ) -> None:
        self._sm = sessionmaker
        self._gw = gateway
        self._embed = embedder
        self._vs = vector_store
        self._win = working_window
        self._ep = episodic_limit
        self._k = long_term_k

    async def recall(
        self,
        *,
        user_id: UUID,
        session_id: UUID | None,
        query: str,
    ) -> RecallResult:
        out = RecallResult()
        # Working memory: last N messages of the current session.
        if session_id is not None:
            async with self._sm() as s:
                msgs = await SqlChatRepository(s).list_messages(
                    user_id=user_id, session_id=session_id
                )
                for m in msgs[-self._win :]:
                    out.working_messages.append(
                        {"role": m.role, "content": m.content}
                    )
        # Episodic: most recent summaries.
        async with self._sm() as s:
            eps = await SqlMemoryRepository(s).list_episodic(
                user_id=user_id, limit=self._ep
            )
            out.episodic_summaries = [e.summary for e in eps]

        # Long-term: vector search over the user's memory collection.
        try:
            vecs = await self._embed.embed(user_id=user_id, texts=[query])
            if vecs:
                coll = vector_collection_for_user_memory(str(user_id))
                matches = await self._vs.query(
                    collection=coll, embedding=vecs[0], k=self._k
                )
                out.long_term = [
                    RecalledLongTerm(
                        id=m.id,
                        kind=str((m.metadata or {}).get("kind", "fact")),
                        content=m.text,
                        score=m.score,
                    )
                    for m in matches
                ]
        except Exception:
            pass
        return out

    async def store_long_term(
        self,
        *,
        user_id: UUID,
        items: list[tuple[str, str, float]],  # [(kind, content, weight)]
        source_session_id: UUID | None = None,
    ) -> None:
        if not items:
            return
        texts = [c for _, c, _ in items]
        try:
            vectors = await self._embed.embed(user_id=user_id, texts=texts)
        except Exception:
            vectors = [[0.0]] * len(texts)
        async with self._sm() as s:
            repo = SqlMemoryRepository(s)
            saved = []
            for (kind, content, weight) in items:
                row = await repo.add_long_term(
                    user_id=user_id,
                    kind=kind,
                    content=content,
                    weight=weight,
                    source_session_id=source_session_id,
                )
                saved.append(row)
        try:
            coll = vector_collection_for_user_memory(str(user_id))
            records = [
                VectorRecord(
                    id=str(saved[i].id),
                    text=texts[i],
                    metadata={"kind": items[i][0], "user_id": str(user_id)},
                )
                for i in range(len(saved))
            ]
            await self._vs.upsert(
                collection=coll, records=records, embeddings=vectors
            )
        except Exception:
            pass
