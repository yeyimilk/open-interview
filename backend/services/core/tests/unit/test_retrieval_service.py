from __future__ import annotations

import uuid

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from openinterview_core.domain.retrieval import InProcessRetrievalService
from openinterview_core.infra.db.common_kb_repository import SqlCommonKBRepository
from openinterview_core.infra.db.memory_repository import SqlMemoryRepository
from openinterview_core.infra.vector import (
    InMemoryVectorStore,
    VectorRecord,
    vector_collection_for_user_memory,
    vector_collection_for_user_project,
)
from openinterview_db import Base, Project, Resume, User
from openinterview_schemas import (
    EmbeddingResponse,
    RetrieveRequest,
    RetrievalPurpose,
    RetrievalSource,
    TokenUsage,
)


class FakeGateway:
    def __init__(self, *, fail_embed: bool = False) -> None:
        self.fail_embed = fail_embed

    async def embed(self, *, user_id, logical_model, inputs):
        if self.fail_embed:
            raise RuntimeError("embed unavailable")
        return EmbeddingResponse(
            model="fake",
            provider="fake",
            vectors=[[1.0, 0.0, 0.0, 0.0] for _ in inputs],
            usage=TokenUsage(prompt_tokens=len(inputs), total_tokens=len(inputs)),
        )


@pytest.fixture()
async def retrieval_env(tmp_path):
    db_path = tmp_path / "retrieval.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    vs = InMemoryVectorStore()
    yield sm, vs
    await engine.dispose()


async def _seed_user(sm, user_id: uuid.UUID, email: str) -> None:
    async with sm() as s:
        s.add(
            User(
                id=user_id,
                email=email,
                display_name=email,
                password_hash="x",
                tier="free",
                is_admin=False,
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_project_query_returns_cited_project_chunks(retrieval_env) -> None:
    sm, vs = retrieval_env
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    await _seed_user(sm, user_id, "project@x.com")
    async with sm() as s:
        s.add(
            Project(
                id=project_id,
                user_id=user_id,
                name="demo",
                source_type="zip",
                status="ready",
            )
        )
        await s.commit()
    await vs.upsert(
        collection=vector_collection_for_user_project(str(user_id), str(project_id)),
        records=[
            VectorRecord(
                id="chunk-1",
                text="FastAPI endpoint uses async repository calls.",
                metadata={
                    "kind": "code",
                    "rel_path": "api.py",
                    "start_line": 10,
                    "end_line": 18,
                },
            )
        ],
        embeddings=[[1.0, 0.0, 0.0, 0.0]],
    )
    svc = InProcessRetrievalService(
        sessionmaker=sm, gateway=FakeGateway(), vector_store=vs
    )

    result = await svc.retrieve(
        RetrieveRequest(
            user_id=user_id,
            query="FastAPI async endpoint",
            purpose=RetrievalPurpose.mentor,
            sources=[RetrievalSource.project],
            project_ids=[project_id],
        )
    )

    assert result.chunks
    first = result.chunks[0]
    assert first.source == RetrievalSource.project
    assert first.citation.project_id == project_id
    assert first.citation.rel_path == "api.py"
    assert first.citation.start_line == 10
    assert "FastAPI endpoint" in result.context_text


@pytest.mark.asyncio
async def test_common_kb_falls_back_to_sql_when_embeddings_fail(retrieval_env) -> None:
    sm, vs = retrieval_env
    user_id = uuid.uuid4()
    await _seed_user(sm, user_id, "common@x.com")
    async with sm() as s:
        repo = SqlCommonKBRepository(s)
        space = await repo.get_or_create_space(key="system_design", name="System Design")
        await repo.create_item(
            space_id=space.id,
            source_id=None,
            document_id=None,
            item_type="note",
            category="system_design",
            title="Consistent hashing",
            question="Explain consistent hashing.",
            answer_outline="Discuss ring placement, virtual nodes, and rebalancing.",
            tags=["hashing"],
        )
    svc = InProcessRetrievalService(
        sessionmaker=sm, gateway=FakeGateway(fail_embed=True), vector_store=vs
    )

    result = await svc.retrieve(
        RetrieveRequest(
            user_id=user_id,
            query="consistent hashing",
            sources=[RetrievalSource.common_kb],
            categories=["system_design"],
        )
    )

    assert [c.source for c in result.chunks] == [RetrievalSource.common_kb]
    assert "Consistent hashing" in result.context_text


@pytest.mark.asyncio
async def test_mixed_workspace_retrieval_merges_sources_without_duplicates(
    retrieval_env,
) -> None:
    sm, vs = retrieval_env
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    resume_id = uuid.uuid4()
    await _seed_user(sm, user_id, "mixed@x.com")
    async with sm() as s:
        s.add(
            Project(
                id=project_id,
                user_id=user_id,
                name="search",
                source_type="zip",
                status="ready",
            )
        )
        s.add(
            Resume(
                id=resume_id,
                user_id=user_id,
                original_filename="resume.md",
                content_type="text/markdown",
                text="Built a hybrid search service.",
                parsed={
                    "skills": ["FastAPI", "Postgres"],
                    "claims": [{"text": "Built a hybrid search service."}],
                },
            )
        )
        await s.commit()
    async with sm() as s:
        mem = await SqlMemoryRepository(s).add_long_term(
            user_id=user_id,
            kind="gap",
            content="Needs more depth on retrieval evaluation.",
            weight=0.9,
        )
    await vs.upsert(
        collection=vector_collection_for_user_project(str(user_id), str(project_id)),
        records=[
            VectorRecord(
                id="project-chunk",
                text="Hybrid search combines vector retrieval and SQL filters.",
                metadata={"rel_path": "search.py", "start_line": 1, "end_line": 5},
            )
        ],
        embeddings=[[1.0, 0.0, 0.0, 0.0]],
    )
    await vs.upsert(
        collection=vector_collection_for_user_memory(str(user_id)),
        records=[
            VectorRecord(
                id=str(mem.id),
                text=mem.content,
                metadata={"kind": mem.kind, "user_id": str(user_id)},
            )
        ],
        embeddings=[[1.0, 0.0, 0.0, 0.0]],
    )
    svc = InProcessRetrievalService(
        sessionmaker=sm, gateway=FakeGateway(), vector_store=vs
    )

    result = await svc.retrieve(
        RetrieveRequest(
            user_id=user_id,
            query="hybrid retrieval evaluation",
            purpose=RetrievalPurpose.general_chat,
            sources=[
                RetrievalSource.project,
                RetrievalSource.resume,
                RetrievalSource.long_term_memory,
            ],
            top_k=10,
        )
    )

    sources = {c.source for c in result.chunks}
    assert RetrievalSource.project in sources
    assert RetrievalSource.resume in sources
    assert RetrievalSource.long_term_memory in sources
    assert len({(c.source, c.id) for c in result.chunks}) == len(result.chunks)


@pytest.mark.asyncio
async def test_workspace_project_retrieval_is_user_scoped(retrieval_env) -> None:
    sm, vs = retrieval_env
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    other_project_id = uuid.uuid4()
    await _seed_user(sm, user_id, "a@x.com")
    await _seed_user(sm, other_user_id, "b@x.com")
    async with sm() as s:
        s.add_all(
            [
                Project(
                    id=project_id,
                    user_id=user_id,
                    name="mine",
                    source_type="zip",
                    status="ready",
                ),
                Project(
                    id=other_project_id,
                    user_id=other_user_id,
                    name="other",
                    source_type="zip",
                    status="ready",
                ),
            ]
        )
        await s.commit()
    await vs.upsert(
        collection=vector_collection_for_user_project(str(other_user_id), str(other_project_id)),
        records=[VectorRecord(id="other", text="secret other-user code", metadata={})],
        embeddings=[[1.0, 0.0, 0.0, 0.0]],
    )
    svc = InProcessRetrievalService(
        sessionmaker=sm, gateway=FakeGateway(), vector_store=vs
    )

    result = await svc.retrieve(
        RetrieveRequest(
            user_id=user_id,
            query="secret code",
            purpose=RetrievalPurpose.general_chat,
            sources=[RetrievalSource.project],
        )
    )

    assert result.chunks == []
