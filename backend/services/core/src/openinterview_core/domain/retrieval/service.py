from __future__ import annotations

import time
from collections import defaultdict
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_logging import get_logger
from openinterview_schemas import (
    Citation,
    RetrieveRequest,
    RetrieveResponse,
    RetrievedChunk,
    RetrievalPurpose,
    RetrievalSource,
)

from ...infra.db.chat_repository import SqlChatRepository
from ...infra.db.memory_repository import SqlMemoryRepository
from ...infra.db.project_repository import SqlProjectRepository
from ...infra.db.qa_repository import SqlQARepository
from ...infra.db.resume_repository import SqlResumeRepository
from ...infra.vector import (
    VectorStore,
    vector_collection_for_user_memory,
    vector_collection_for_user_project,
)
from ..kb import CommonKBRetriever
from ..projects.embedder import GatewayEmbedder

log = get_logger(__name__)


class RetrievalService(Protocol):
    async def retrieve(self, request: RetrieveRequest) -> RetrieveResponse: ...


class InProcessRetrievalService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        gateway,
        vector_store: VectorStore,
        embed_logical_model: str = "embed-default",
    ) -> None:
        self._sm = sessionmaker
        self._gw = gateway
        self._vs = vector_store
        self._embed = GatewayEmbedder(gateway, logical_model=embed_logical_model)
        self._common = CommonKBRetriever(
            sessionmaker=sessionmaker,
            gateway=gateway,
            vector_store=vector_store,
            logical_model=embed_logical_model,
        )

    async def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
        started = time.perf_counter()
        sources = request.sources or _default_sources(request.purpose)
        chunks: list[RetrievedChunk] = []

        vector_embedding: list[float] | None = None
        if any(
            s
            in {
                RetrievalSource.project,
                RetrievalSource.long_term_memory,
            }
            for s in sources
        ):
            vector_embedding = await self._embed_query(request)

        for source in sources:
            if source == RetrievalSource.working_memory:
                chunks.extend(await self._working_memory(request))
            elif source == RetrievalSource.episodic_memory:
                chunks.extend(await self._episodic_memory(request))
            elif source == RetrievalSource.long_term_memory:
                chunks.extend(await self._long_term_memory(request, vector_embedding))
            elif source == RetrievalSource.project:
                chunks.extend(await self._project_chunks(request, vector_embedding))
            elif source == RetrievalSource.common_kb:
                chunks.extend(await self._common_kb(request))
            elif source == RetrievalSource.resume:
                chunks.extend(await self._resume_chunks(request))
            elif source == RetrievalSource.resume_claim:
                chunks.extend(await self._resume_claim_chunks(request))
            elif source == RetrievalSource.qa:
                chunks.extend(await self._qa_chunks(request))

        deduped = _dedupe(chunks)
        deduped.sort(key=lambda c: c.score, reverse=True)
        if len(deduped) > request.top_k:
            deduped = deduped[: request.top_k]
        context_text = _context_text(deduped, request.context_char_budget)
        selected = sorted({c.source for c in deduped}, key=lambda s: s.value)
        counts = defaultdict(int)
        for c in deduped:
            counts[c.source.value] += 1
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "retrieval_complete",
            purpose=request.purpose.value,
            sources=[s.value for s in sources],
            selected_sources=[s.value for s in selected],
            result_counts=dict(counts),
            latency_ms=elapsed_ms,
            context_chars=len(context_text),
        )
        return RetrieveResponse(
            chunks=deduped,
            context_text=context_text,
            selected_sources=selected,
            total_chars=len(context_text),
            meta={"latency_ms": elapsed_ms, "result_counts": dict(counts)},
        )

    async def _embed_query(self, request: RetrieveRequest) -> list[float] | None:
        query = request.query.strip()
        if not query:
            return None
        try:
            vectors = await self._embed.embed(user_id=request.user_id, texts=[query])
        except Exception:
            return None
        return vectors[0] if vectors else None

    async def _working_memory(self, request: RetrieveRequest) -> list[RetrievedChunk]:
        if request.session_id is None:
            return []
        async with self._sm() as s:
            msgs = await SqlChatRepository(s).list_messages(
                user_id=request.user_id, session_id=request.session_id
            )
        limit = _source_k(request, RetrievalSource.working_memory, default=12)
        out: list[RetrievedChunk] = []
        for msg in msgs[-limit:]:
            out.append(
                RetrievedChunk(
                    id=str(msg.id),
                    source=RetrievalSource.working_memory,
                    title=f"{msg.role} message",
                    text=msg.content,
                    score=1.0 - (len(out) * 0.001),
                    citation=Citation(
                        source=RetrievalSource.working_memory,
                        title=f"{msg.role} message",
                        metadata={"session_id": str(request.session_id)},
                    ),
                    metadata={"role": msg.role, "created_at": str(msg.created_at)},
                )
            )
        return out

    async def _episodic_memory(self, request: RetrieveRequest) -> list[RetrievedChunk]:
        limit = _source_k(request, RetrievalSource.episodic_memory, default=5)
        async with self._sm() as s:
            rows = await SqlMemoryRepository(s).list_episodic(
                user_id=request.user_id, limit=limit
            )
        return [
            RetrievedChunk(
                id=str(row.id),
                source=RetrievalSource.episodic_memory,
                title="session summary",
                text=row.summary,
                score=0.75,
                citation=Citation(
                    source=RetrievalSource.episodic_memory,
                    title="session summary",
                    metadata={"session_id": str(row.session_id)},
                ),
                metadata={"entities": row.entities or {}},
            )
            for row in rows
        ]

    async def _long_term_memory(
        self, request: RetrieveRequest, embedding: list[float] | None
    ) -> list[RetrievedChunk]:
        limit = _source_k(request, RetrievalSource.long_term_memory, default=6)
        if embedding is not None:
            try:
                matches = await self._vs.query(
                    collection=vector_collection_for_user_memory(str(request.user_id)),
                    embedding=embedding,
                    k=limit,
                )
                return [
                    RetrievedChunk(
                        id=m.id,
                        source=RetrievalSource.long_term_memory,
                        title=str((m.metadata or {}).get("kind") or "memory"),
                        text=m.text,
                        score=m.score,
                        citation=Citation(
                            source=RetrievalSource.long_term_memory,
                            title=str((m.metadata or {}).get("kind") or "memory"),
                        ),
                        metadata=dict(m.metadata or {}),
                    )
                    for m in matches
                ]
            except Exception:
                pass
        async with self._sm() as s:
            rows = await SqlMemoryRepository(s).list_long_term(
                user_id=request.user_id, limit=limit
            )
            rows_by_id = {str(r.id): r for r in rows}
        return [
            RetrievedChunk(
                id=rid,
                source=RetrievalSource.long_term_memory,
                title=row.kind,
                text=row.content,
                score=float(row.weight or 0.0),
                citation=Citation(source=RetrievalSource.long_term_memory, title=row.kind),
                metadata={"kind": row.kind, "weight": row.weight},
            )
            for rid, row in rows_by_id.items()
        ]

    async def _project_chunks(
        self, request: RetrieveRequest, embedding: list[float] | None
    ) -> list[RetrievedChunk]:
        if embedding is None:
            return []
        project_ids = await self._project_ids(request)
        limit = _source_k(request, RetrievalSource.project, default=6)
        out: list[RetrievedChunk] = []
        for project_id in project_ids:
            try:
                matches = await self._vs.query(
                    collection=vector_collection_for_user_project(
                        str(request.user_id), str(project_id)
                    ),
                    embedding=embedding,
                    k=limit,
                )
            except Exception:
                continue
            for m in matches:
                md = dict(m.metadata or {})
                rel_path = str(md.get("rel_path") or "")
                title = rel_path or str(project_id)
                out.append(
                    RetrievedChunk(
                        id=m.id,
                        source=RetrievalSource.project,
                        title=title,
                        text=m.text,
                        score=m.score,
                        citation=Citation(
                            source=RetrievalSource.project,
                            title=title,
                            project_id=project_id,
                            rel_path=rel_path or None,
                            start_line=_int_or_none(md.get("start_line")),
                            end_line=_int_or_none(md.get("end_line")),
                            metadata={"kind": md.get("kind", "")},
                        ),
                        metadata={**md, "project_id": str(project_id)},
                    )
                )
        return out

    async def _common_kb(self, request: RetrieveRequest) -> list[RetrievedChunk]:
        limit = _source_k(request, RetrievalSource.common_kb, default=6)
        matches = await self._common.retrieve(
            user_id=request.user_id,
            query=request.query,
            space_keys=request.space_keys,
            categories=request.categories,
            company=request.company,
            languages=request.languages,
            k=limit,
        )
        return [
            RetrievedChunk(
                id=m.id,
                source=RetrievalSource.common_kb,
                title=m.title,
                text=m.text,
                score=m.score,
                citation=Citation(
                    source=RetrievalSource.common_kb,
                    title=m.title,
                    metadata={
                        "source": m.source,
                        "category": m.category,
                        "company": m.company,
                        "language": m.language,
                    },
                ),
                metadata={
                    "source": m.source,
                    "category": m.category,
                    "company": m.company,
                    "language": m.language,
                    "tags": m.tags,
                },
            )
            for m in matches
        ]

    async def _resume_chunks(self, request: RetrieveRequest) -> list[RetrievedChunk]:
        limit = _source_k(request, RetrievalSource.resume, default=4)
        async with self._sm() as s:
            repo = SqlResumeRepository(s)
            if request.resume_ids:
                rows = []
                for rid in request.resume_ids:
                    row = await repo.get(user_id=request.user_id, resume_id=rid)
                    if row is not None:
                        rows.append(row)
            else:
                rows = await repo.list_for_user(user_id=request.user_id)
        out: list[RetrievedChunk] = []
        for row in rows[:limit]:
            text = _resume_text(row)
            if not text:
                continue
            out.append(
                RetrievedChunk(
                    id=str(row.id),
                    source=RetrievalSource.resume,
                    title=row.original_filename,
                    text=text,
                    score=_keyword_score(request.query, text, base=0.45),
                    citation=Citation(
                        source=RetrievalSource.resume,
                        title=row.original_filename,
                        resume_id=row.id,
                    ),
                    metadata={"filename": row.original_filename},
                )
            )
        return out

    async def _resume_claim_chunks(self, request: RetrieveRequest) -> list[RetrievedChunk]:
        limit = _source_k(request, RetrievalSource.resume_claim, default=6)
        async with self._sm() as s:
            repo = SqlResumeRepository(s)
            if request.resume_ids:
                resumes = []
                for rid in request.resume_ids:
                    row = await repo.get(user_id=request.user_id, resume_id=rid)
                    if row is not None:
                        resumes.append(row)
            else:
                resumes = await repo.list_for_user(user_id=request.user_id)
            mappings = []
            for resume in resumes:
                mappings.extend(
                    await repo.list_mappings(user_id=request.user_id, resume_id=resume.id)
                )
        chunks = [
            RetrievedChunk(
                id=str(row.id),
                source=RetrievalSource.resume_claim,
                title="resume claim",
                text=row.claim,
                score=_keyword_score(request.query, row.claim, base=row.confidence / 100.0),
                citation=Citation(
                    source=RetrievalSource.resume_claim,
                    title="resume claim",
                    resume_id=row.resume_id,
                    project_id=row.project_id,
                    metadata={"confidence": row.confidence},
                ),
                metadata={
                    "confidence": row.confidence,
                    "grounding": row.grounding or [],
                },
            )
            for row in mappings
        ]
        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks[:limit]

    async def _qa_chunks(self, request: RetrieveRequest) -> list[RetrievedChunk]:
        if not request.qa_set_ids:
            return []
        limit = _source_k(request, RetrievalSource.qa, default=6)
        rows = []
        async with self._sm() as s:
            repo = SqlQARepository(s)
            for qa_set_id in request.qa_set_ids:
                rows.extend(
                    await repo.list_items(user_id=request.user_id, qa_set_id=qa_set_id)
                )
        chunks = [
            RetrievedChunk(
                id=str(row.id),
                source=RetrievalSource.qa,
                title=row.question[:80],
                text=f"Q: {row.question}\nA: {row.ideal_answer}",
                score=_keyword_score(request.query, f"{row.question} {row.ideal_answer}", base=0.35),
                citation=Citation(
                    source=RetrievalSource.qa,
                    title=row.question[:80],
                    qa_set_id=row.qa_set_id,
                    metadata={"category": row.category, "difficulty": row.difficulty},
                ),
                metadata={"category": row.category, "tags": row.tags or []},
            )
            for row in rows
        ]
        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks[:limit]

    async def _project_ids(self, request: RetrieveRequest) -> list[UUID]:
        if request.project_ids:
            if request.purpose == RetrievalPurpose.qa_generation:
                return request.project_ids
            out: list[UUID] = []
            async with self._sm() as s:
                repo = SqlProjectRepository(s)
                for pid in request.project_ids:
                    if await repo.get(user_id=request.user_id, project_id=pid):
                        out.append(pid)
            return out
        async with self._sm() as s:
            rows = await SqlProjectRepository(s).list(user_id=request.user_id)
        return [p.id for p in rows if p.status == "ready"]


def _default_sources(purpose: RetrievalPurpose) -> list[RetrievalSource]:
    if purpose == RetrievalPurpose.general_chat:
        return [
            RetrievalSource.working_memory,
            RetrievalSource.long_term_memory,
            RetrievalSource.project,
            RetrievalSource.resume,
            RetrievalSource.common_kb,
        ]
    if purpose == RetrievalPurpose.mentor:
        return [
            RetrievalSource.working_memory,
            RetrievalSource.episodic_memory,
            RetrievalSource.long_term_memory,
            RetrievalSource.project,
            RetrievalSource.common_kb,
        ]
    if purpose == RetrievalPurpose.interviewer:
        return [RetrievalSource.long_term_memory, RetrievalSource.common_kb]
    if purpose in {RetrievalPurpose.qa_generation, RetrievalPurpose.claim_mapping}:
        return [RetrievalSource.project]
    return [RetrievalSource.project, RetrievalSource.common_kb]


def _source_k(request: RetrieveRequest, source: RetrievalSource, *, default: int) -> int:
    raw = (
        request.per_source_top_k.get(source.value)
        or request.per_source_top_k.get(source.name)
        or default
    )
    try:
        return max(1, min(50, int(raw)))
    except Exception:
        return default


def _dedupe(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    out: list[RetrievedChunk] = []
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        text_key = " ".join(chunk.text.split())[:240].lower()
        key = (chunk.source.value, chunk.id or text_key)
        fuzzy = (chunk.source.value, text_key)
        if key in seen or fuzzy in seen:
            continue
        seen.add(key)
        seen.add(fuzzy)
        out.append(chunk)
    return out


def _context_text(chunks: list[RetrievedChunk], budget: int) -> str:
    parts: list[str] = []
    used = 0
    for chunk in chunks:
        label = _label(chunk)
        text = chunk.text.strip()
        if not text:
            continue
        block = f"[{label}]\n{text}"
        remaining = max(0, budget - used)
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[:remaining].rstrip()
        parts.append(block)
        used += len(block) + 2
    return "\n\n".join(parts)


def _label(chunk: RetrievedChunk) -> str:
    c = chunk.citation
    if chunk.source == RetrievalSource.project and c.rel_path:
        if c.start_line and c.end_line:
            return f"project:{c.rel_path}:{c.start_line}-{c.end_line}"
        return f"project:{c.rel_path}"
    if chunk.source == RetrievalSource.common_kb:
        source = chunk.metadata.get("source") or "common"
        category = chunk.metadata.get("category") or "general"
        return f"{source}/{category}: {chunk.title or chunk.id}"
    if chunk.source in {RetrievalSource.resume, RetrievalSource.resume_claim}:
        return f"{chunk.source.value}: {chunk.title or chunk.id}"
    if chunk.source == RetrievalSource.qa:
        return f"qa:{chunk.metadata.get('category') or 'general'}"
    return f"{chunk.source.value}: {chunk.title or chunk.id}"


def _resume_text(row) -> str:
    parsed = row.parsed if isinstance(row.parsed, dict) else {}
    lines: list[str] = [f"Resume: {row.original_filename}"]
    skills = parsed.get("skills") if isinstance(parsed, dict) else None
    if isinstance(skills, list) and skills:
        lines.append("Skills: " + ", ".join(str(x) for x in skills[:20]))
    claims = parsed.get("claims") if isinstance(parsed, dict) else None
    if isinstance(claims, list) and claims:
        lines.append("Claims:")
        for c in claims[:8]:
            if isinstance(c, dict):
                txt = str(c.get("text") or "").strip()
            else:
                txt = str(c).strip()
            if txt:
                lines.append(f"- {txt}")
    projects = parsed.get("projects") if isinstance(parsed, dict) else None
    if isinstance(projects, list) and projects:
        lines.append("Projects:")
        for p in projects[:5]:
            if isinstance(p, dict):
                name = str(p.get("name") or "").strip()
                summary = str(p.get("summary") or "").strip()
                lines.append(f"- {name}: {summary}".strip())
    if len(lines) == 1 and row.text:
        lines.append(row.text[:1200])
    return "\n".join(lines)[:2000]


def _keyword_score(query: str, text: str, *, base: float) -> float:
    q = {w.lower() for w in query.split() if len(w) > 2}
    if not q:
        return base
    t = text.lower()
    hits = sum(1 for w in q if w in t)
    return min(1.0, base + 0.05 * hits)


def _int_or_none(value) -> int | None:
    try:
        i = int(value)
    except Exception:
        return None
    return i or None
