"""QA generation pipeline test using a fake gateway."""
from __future__ import annotations

import asyncio
import json
import os
import re
from uuid import uuid4

import pytest

pytest.importorskip("aiosqlite")

from openinterview_core.config import Settings
from openinterview_core.domain.qa import QAGenerationService
from openinterview_core.domain.question_sets import (
    QuestionSetGenerationRequest,
    QuestionSetService,
)
from openinterview_core.infra.db import Database
from openinterview_core.infra.db.qa_repository import SqlQARepository
from openinterview_core.infra.vector import (
    InMemoryVectorStore,
    VectorRecord,
    vector_collection_for_user_project,
)
from openinterview_db import Base, Project, Resume, User
from openinterview_schemas import (
    ChatCompletionResponse,
    EmbeddingResponse,
    TokenUsage,
)


class FakeGateway:
    def __init__(self) -> None:
        self.chat_calls = 0

    async def chat(self, *, user_id, logical_model, messages, **kwargs):
        self.chat_calls += 1
        prompt = messages[-1].content
        if "design an interview question plan" in prompt:
            # Planner refinement -> just return original categories.
            return _resp(json.dumps({"shards": []}))
        if (
            "interview questions" in prompt
            or "Generate interview questions" in prompt
            or "high-signal interview" in prompt
        ):
            # Generator -> include category from prompt so each shard yields a unique question.
            cat_match = re.search(r"CATEGORY:\s*(\w+)", prompt)
            cat = cat_match.group(1) if cat_match else "general"
            data = {
                "items": [
                    {
                        "question": f"[{cat}] How does your API handle async errors?",
                        "ideal_answer": "We use FastAPI exception handlers.",
                        "evidence_indices": [0],
                        "difficulty": 3,
                        "tags": ["fastapi", cat],
                        "follow_up_axes": ["implementation_details", "trade-offs"],
                    }
                ]
            }
            return _resp(json.dumps(data))
        return _resp("{}")

    async def embed(self, *, user_id, logical_model, inputs):
        return EmbeddingResponse(
            model="x", provider="x",
            vectors=[[1.0, 0.0, 0.0, 0.0] for _ in inputs],
            usage=TokenUsage(prompt_tokens=1, total_tokens=1),
        )


class FailingGenerationGateway(FakeGateway):
    async def chat(self, *, user_id, logical_model, messages, **kwargs):
        prompt = messages[-1].content
        if "designing an interview question plan" in prompt:
            return _resp(json.dumps({"shards": []}))
        raise RuntimeError("generator unavailable")


def _resp(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="x", model="m", provider="p", content=content,
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
    )


@pytest.mark.asyncio
async def test_qa_generation_creates_set_and_items(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/qa.db"
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/qa.db")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed a user + project + one chunk in vector store.
    user_id = uuid4()
    project_id = uuid4()
    async with db.sessionmaker() as s:
        s.add(User(
            id=user_id, email="u@x.com", display_name="u",
            password_hash="x", tier="free", is_admin=False,
        ))
        s.add(Project(
            id=project_id, user_id=user_id, name="demo",
            source_type="zip", status="ready",
            summary="A FastAPI calculator", architecture={"summary": "tiny"},
        ))
        await s.commit()

    vs = InMemoryVectorStore()
    coll = vector_collection_for_user_project(str(user_id), str(project_id))
    await vs.upsert(
        collection=coll,
        records=[VectorRecord(
            id="r1",
            text="def add(a, b): return a + b",
            metadata={"rel_path": "calc.py", "start_line": 1, "end_line": 1, "kind": "code"},
        )],
        embeddings=[[1.0, 0.0, 0.0, 0.0]],
    )

    svc = QAGenerationService(
        sessionmaker=db.sessionmaker,
        gateway=FakeGateway(),
        vector_store=vs,
        max_total_per_set=10,
    )
    qa_set_id = await svc.run(
        user_id=user_id, project_id=project_id,
        position="swe_generic", level="mid",
    )

    async with db.sessionmaker() as s:
        repo = SqlQARepository(s)
        qa_set = await repo.get_set(user_id=user_id, qa_set_id=qa_set_id)
        items = await repo.list_items(user_id=user_id, qa_set_id=qa_set_id)
        run = await repo.latest_generation_run(qa_set_id=qa_set_id)
        shards = await repo.list_generation_shards(run_id=run.id) if run else []

    assert qa_set is not None
    assert qa_set.status == "ready"
    assert qa_set.total >= 1
    assert items
    cats = {it.category for it in items}
    # Multiple shards => multiple categories.
    assert len(cats) >= 2
    # Evidence is propagated.
    any_with_evidence = any(it.evidence for it in items)
    assert any_with_evidence
    assert items[0].follow_up_axes[:2] == [
        "implementation_details",
        "trade_offs",
    ]
    assert run is not None
    assert run.status == "ready"
    assert run.attempt == 1
    assert shards
    assert all(shard.status == "ready" for shard in shards)

    await db.dispose()


@pytest.mark.asyncio
async def test_question_set_service_generates_resume_set(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/resume_qa.db")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    user_id = uuid4()
    resume_id = uuid4()
    async with db.sessionmaker() as s:
        s.add(User(
            id=user_id, email="r@x.com", display_name="u",
            password_hash="x", tier="free", is_admin=False,
        ))
        s.add(Resume(
            id=resume_id,
            user_id=user_id,
            original_filename="resume.pdf",
            content_type="application/pdf",
            text="Ada Staff SWE",
            parsed={
                "name": "Ada",
                "skills": ["FastAPI"],
                "claims": [{"text": "Built async API", "section": "experience"}],
            },
        ))
        await s.commit()

    svc = QuestionSetService(
        sessionmaker=db.sessionmaker,
        gateway=FakeGateway(),
        vector_store=InMemoryVectorStore(),
        max_total_per_set=10,
    )
    result = await svc.generate(
        QuestionSetGenerationRequest(
            user_id=user_id,
            resume_id=resume_id,
            position="swe_generic",
            level="mid",
            scope="resume",
        )
    )

    async with db.sessionmaker() as s:
        repo = SqlQARepository(s)
        qa_set = await repo.get_set(user_id=user_id, qa_set_id=result.qa_set_id)
        items = await repo.list_items(user_id=user_id, qa_set_id=result.qa_set_id)
        run = await repo.latest_generation_run(qa_set_id=result.qa_set_id)

    assert qa_set is not None
    assert qa_set.scope == "resume"
    assert qa_set.resume_id == resume_id
    assert qa_set.status == "ready"
    assert items
    assert items[0].follow_up_axes
    assert run is not None
    assert run.meta["item_count"] == qa_set.total

    await db.dispose()


@pytest.mark.asyncio
async def test_question_set_service_marks_failed_when_all_shards_fail(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/qa_fail.db")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    user_id = uuid4()
    project_id = uuid4()
    async with db.sessionmaker() as s:
        s.add(User(
            id=user_id, email="fail@x.com", display_name="u",
            password_hash="x", tier="free", is_admin=False,
        ))
        s.add(Project(
            id=project_id, user_id=user_id, name="demo",
            source_type="zip", status="ready",
            summary="A FastAPI calculator", architecture={"summary": "tiny"},
        ))
        await s.commit()

    svc = QuestionSetService(
        sessionmaker=db.sessionmaker,
        gateway=FailingGenerationGateway(),
        vector_store=InMemoryVectorStore(),
    )

    with pytest.raises(RuntimeError):
        await svc.generate(
            QuestionSetGenerationRequest(
                user_id=user_id,
                project_id=project_id,
                position="swe_generic",
                level="mid",
                scope="project",
            )
        )

    async with db.sessionmaker() as s:
        repo = SqlQARepository(s)
        qa_set = await repo.get_or_create_set(
            user_id=user_id,
            project_id=project_id,
            position="swe_generic",
            level="mid",
        )
        run = await repo.latest_generation_run(qa_set_id=qa_set.id)
        shards = await repo.list_generation_shards(run_id=run.id) if run else []

    assert qa_set.status == "failed"
    assert "all question generation shards failed" in (qa_set.error or "")
    assert run is not None
    assert run.status == "failed"
    assert shards
    assert all(shard.status == "failed" for shard in shards)

    await db.dispose()


@pytest.mark.asyncio
async def test_question_set_retry_clears_previous_error(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/qa_retry.db")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    user_id = uuid4()
    project_id = uuid4()
    async with db.sessionmaker() as s:
        s.add(User(
            id=user_id, email="retry@x.com", display_name="u",
            password_hash="x", tier="free", is_admin=False,
        ))
        s.add(Project(
            id=project_id, user_id=user_id, name="demo",
            source_type="zip", status="ready",
            summary="A FastAPI calculator", architecture={"summary": "tiny"},
        ))
        repo = SqlQARepository(s)
        qa_set = await repo.get_or_create_set(
            user_id=user_id,
            project_id=project_id,
            position="swe_generic",
            level="mid",
        )
        await repo.set_status(qa_set_id=qa_set.id, status="failed", error="boom")
        await s.commit()

    svc = QuestionSetService(
        sessionmaker=db.sessionmaker,
        gateway=FakeGateway(),
        vector_store=InMemoryVectorStore(),
        max_total_per_set=10,
    )
    result = await svc.generate(
        QuestionSetGenerationRequest(
            user_id=user_id,
            project_id=project_id,
            position="swe_generic",
            level="mid",
            scope="project",
        )
    )

    async with db.sessionmaker() as s:
        qa_set = await SqlQARepository(s).get_set(
            user_id=user_id, qa_set_id=result.qa_set_id
        )

    assert qa_set is not None
    assert qa_set.status == "ready"
    assert qa_set.error is None

    await db.dispose()
