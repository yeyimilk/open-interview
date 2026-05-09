from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from openinterview_core.domain.interviewer import InterviewBlueprintService
from openinterview_core.domain.kb import CommonDocumentTextExtractor
from openinterview_core.infra.db.common_kb_repository import SqlCommonKBRepository, normalize_tag
from openinterview_db import Base

_seed_path = Path(__file__).resolve().parents[5] / "scripts" / "seed_common_kb.py"
_seed_spec = importlib.util.spec_from_file_location("seed_common_kb", _seed_path)
assert _seed_spec and _seed_spec.loader
_seed_module = importlib.util.module_from_spec(_seed_spec)
sys.modules["seed_common_kb"] = _seed_module
_seed_spec.loader.exec_module(_seed_module)
SEED_ITEMS = _seed_module.ITEMS
SEED_SOURCES = _seed_module.SOURCES


@pytest.fixture()
async def kb_env(tmp_path):
    db_path = tmp_path / "common_kb.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    yield sm
    await engine.dispose()


def test_common_doc_extractor_handles_csv_and_json() -> None:
    ext = CommonDocumentTextExtractor()
    csv_text = ext.extract(
        filename="items.csv",
        content_type="text/csv",
        data=b"title,company\nDesign feed,Meta\n",
    )
    assert "title: Design feed" in csv_text
    assert "company: Meta" in csv_text

    json_text = ext.extract(
        filename="items.json",
        content_type="application/json",
        data=b'{"question":"Explain consistent hashing","tags":["system-design"]}',
    )
    assert "question: Explain consistent hashing" in json_text
    assert "tags[0]: system-design" in json_text


def test_normalize_tag_is_stable() -> None:
    assert normalize_tag("Graph DP / Two Pointers") == "graph-dp-two-pointers"


def test_public_seed_pack_keeps_leetcode_metadata_only() -> None:
    leetcode = [item for item in SEED_ITEMS if item.source == "leetcode_topics"]
    assert leetcode
    assert SEED_SOURCES["leetcode_topics"]["license"].startswith("metadata-only")
    for item in leetcode:
        assert item.question is None
        assert item.answer_outline is None
        assert "solution" not in (item.content or "").lower()
        assert item.provenance and item.provenance.get("stored")


@pytest.mark.asyncio
async def test_blueprint_precedence_session_over_saved_and_company(kb_env) -> None:
    user_id = uuid.uuid4()
    async with kb_env() as s:
        repo = SqlCommonKBRepository(s)
        space = await repo.get_or_create_space(key="company_experience", name="Company")
        await repo.create_item(
            space_id=space.id,
            source_id=None,
            document_id=None,
            item_type="company_experience",
            category="system_design",
            title="Meta system design round",
            question="Design a feed.",
            answer_outline="Discuss ranking, fanout, cache, and trade-offs.",
            company="Meta",
            language="Python",
            tags=["meta", "system-design"],
        )
        await repo.rebuild_company_profiles(company_key="meta")
        await repo.upsert_user_preferences(
            user_id=user_id,
            target_company="Meta",
            category_weights={"algorithms": 0.2, "system_design": 1.0},
            languages=["Python"],
            interview_style="realistic",
            include_company_style=True,
        )

    bp = await InterviewBlueprintService(sessionmaker=kb_env).build(
        user_id=user_id,
        position="swe_generic",
        level="mid",
        n_questions=6,
        target_company="Meta",
        session_preferences={
            "category_weights": {"algorithms": 3.0},
            "languages": ["Java"],
            "include_company_style": True,
        },
    )
    assert bp.target_company == "Meta"
    assert bp.languages == ["Java"]
    assert bp.category_weights["algorithms"] > bp.category_weights["system_design"]
    assert bp.n_questions == 6


@pytest.mark.asyncio
async def test_delete_document_removes_related_items_and_tags(kb_env) -> None:
    async with kb_env() as s:
        repo = SqlCommonKBRepository(s)
        space = await repo.get_or_create_space(key="leetcode", name="LeetCode")
        doc = await repo.create_document(
            space_id=space.id,
            source_id=None,
            title="Graph set",
            filename="graphs.md",
            content_type="text/markdown",
            blob_path="common/kb/documents/test/graphs.md",
            meta={"tags": ["graph"]},
        )
        item = await repo.create_item(
            space_id=space.id,
            source_id=None,
            document_id=doc.id,
            item_type="question",
            category="algorithms",
            title="Shortest path",
            question="When would you use Dijkstra?",
            tags=["graph", "dijkstra"],
        )

        refs = await repo.document_item_refs(doc.id)
        assert refs == [(item.id, "leetcode")]
        assert (await repo.list_items(tag="dijkstra"))[0].id == item.id

        assert await repo.delete_document_with_items(doc.id)
        assert await repo.get_document(doc.id) is None
        assert await repo.list_items(tag="dijkstra") == []
        assert await repo.item_tags([item.id]) == {}
