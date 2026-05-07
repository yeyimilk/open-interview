from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...infra.db.common_kb_repository import SqlCommonKBRepository
from ...infra.vector import VectorStore, vector_collection_for_common_kb
from ..projects.embedder import GatewayEmbedder


@dataclass(frozen=True)
class CommonKBMatch:
    id: str
    title: str
    category: str
    source: str
    text: str
    score: float = 0.0
    company: str | None = None
    language: str | None = None
    tags: list[str] = field(default_factory=list)


class CommonKBRetriever:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        gateway,
        vector_store: VectorStore,
        logical_model: str = "embed-default",
    ) -> None:
        self._sm = sessionmaker
        self._embed = GatewayEmbedder(gateway, logical_model=logical_model)
        self._vs = vector_store

    async def retrieve(
        self,
        *,
        user_id: UUID,
        query: str,
        space_keys: list[str] | None = None,
        categories: list[str] | None = None,
        company: str | None = None,
        languages: list[str] | None = None,
        k: int = 6,
    ) -> list[CommonKBMatch]:
        async with self._sm() as s:
            repo = SqlCommonKBRepository(s)
            spaces = await repo.list_spaces(enabled_only=True)
            if space_keys:
                wanted = set(space_keys)
                spaces = [sp for sp in spaces if sp.key in wanted]
        try:
            vecs = await self._embed.embed(user_id=user_id, texts=[query])
        except Exception:
            vecs = []
        if not vecs:
            return await self._fallback(
                space_keys=[sp.key for sp in spaces],
                categories=categories,
                company=company,
                languages=languages,
                limit=k,
            )
        matches: list[CommonKBMatch] = []
        for sp in spaces:
            try:
                for m in await self._vs.query(
                    collection=vector_collection_for_common_kb(sp.key),
                    embedding=vecs[0],
                    k=k,
                ):
                    md = m.metadata or {}
                    if categories and md.get("category") not in categories:
                        continue
                    if company and company.lower() not in str(md.get("company") or "").lower():
                        continue
                    if languages and str(md.get("language") or "").lower() not in {x.lower() for x in languages}:
                        continue
                    matches.append(
                        CommonKBMatch(
                            id=m.id,
                            title=str(md.get("title") or m.text[:80]),
                            category=str(md.get("category") or "general"),
                            source=f"common:{sp.key}",
                            text=m.text[:1200],
                            score=m.score,
                            company=str(md.get("company") or "") or None,
                            language=str(md.get("language") or "") or None,
                        )
                    )
            except Exception:
                continue
        matches.sort(key=lambda x: x.score, reverse=True)
        if matches:
            return matches[:k]
        return await self._fallback(
            space_keys=[sp.key for sp in spaces],
            categories=categories,
            company=company,
            languages=languages,
            limit=k,
        )

    async def _fallback(
        self,
        *,
        space_keys: list[str],
        categories: list[str] | None,
        company: str | None,
        languages: list[str] | None,
        limit: int,
    ) -> list[CommonKBMatch]:
        out: list[CommonKBMatch] = []
        async with self._sm() as s:
            repo = SqlCommonKBRepository(s)
            for space in space_keys:
                rows = await repo.list_items(
                    space_key=space,
                    company=company,
                    category=categories[0] if categories else None,
                    language=languages[0] if languages else None,
                    limit=limit,
                )
                tag_map = await repo.item_tags([r.id for r in rows])
                for r in rows:
                    text = "\n".join(x for x in [r.question, r.answer_outline, r.content] if x)
                    out.append(
                        CommonKBMatch(
                            id=str(r.id),
                            title=r.title,
                            category=r.category,
                            source=f"common:{space}",
                            text=text[:1200],
                            company=r.company,
                            language=r.language,
                            tags=tag_map.get(r.id, []),
                        )
                    )
        return out[:limit]
