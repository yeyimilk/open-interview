"""Unit tests for the resume-driven QA planner.

The planner is deterministic and just walks parsed-resume JSON + claim
mappings, so we exercise it with hand-crafted fixtures (no LLM)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from uuid import uuid4

from openinterview_core.domain.qa.resume_planner import plan_for_resume


@dataclass
class _MockMapping:
    claim: str
    project_id: object | None
    grounding: list | None = None
    confidence: int = 80


def test_plan_emits_shards_per_top_grounded_claim():
    pid = uuid4()
    mappings = [
        _MockMapping(claim="Cut p99 latency 40%", project_id=pid, confidence=90),
        _MockMapping(claim="Migrated 200k users", project_id=pid, confidence=80),
        _MockMapping(claim="Owned the auth rewrite", project_id=None, confidence=30),
    ]
    parsed = {
        "name": "Ada",
        "skills": ["Postgres", "Kafka", "FastAPI"],
        "experience": [
            {"title": "Staff SWE", "company": "Acme", "bullets": ["Led migration"]},
        ],
        "projects": [
            {"name": "search-svc", "summary": "Hybrid retrieval over Postgres."},
        ],
        "claims": [
            {"text": "Brand new claim not yet mapped", "section": "experience"},
        ],
    }
    shards, ctx = plan_for_resume(
        parsed=parsed, claim_mappings=mappings, position="swe_generic", level="senior"
    )

    cats = [s.category for s in shards]
    # We always get at least one of each major shard type.
    assert "experience_claim" in cats
    assert "skills_breadth" in cats
    assert "project_overview" in cats
    assert "behavioral_grounded" in cats

    # Highest-confidence claim was prioritised first.
    first_claim_shard = next(s for s in shards if s.category == "experience_claim")
    first_ctx = ctx[first_claim_shard.retrieval_query]
    assert "Cut p99 latency" in (first_ctx.claim or "")
    assert first_ctx.source_project_id == str(pid)

    # Skills payload is in context.extra so the generator can use it.
    skills_shard = next(s for s in shards if s.category == "skills_breadth")
    assert ctx[skills_shard.retrieval_query].extra["skills"] == [
        "Postgres",
        "Kafka",
        "FastAPI",
    ]


def test_plan_emits_core_generalist_shards_for_empty_resume():
    """Even with no claims/skills/projects we still build a usable bank:
    a real interviewer would still ask system design + algorithms."""
    shards, ctx = plan_for_resume(
        parsed={}, claim_mappings=[], position="swe_generic", level="mid"
    )
    cats = [s.category for s in shards]
    assert "system_design" in cats
    assert "algorithms" in cats
    assert "architecture" in cats  # mid+ gets architecture
    # Every shard's retrieval_query has a context entry.
    for s in shards:
        assert s.retrieval_query in ctx


def test_plan_scales_with_level():
    """Senior interviews should dig deeper than junior ones."""
    junior, _ = plan_for_resume(
        parsed={}, claim_mappings=[], position="swe_generic", level="junior"
    )
    senior, _ = plan_for_resume(
        parsed={}, claim_mappings=[], position="swe_generic", level="senior"
    )
    # Junior gets system_design + algorithms but no architecture shard.
    assert any(s.category == "system_design" for s in junior)
    assert not any(s.category == "architecture" for s in junior)
    # Senior gets architecture and a heftier algorithms allocation.
    assert any(s.category == "architecture" for s in senior)
    senior_algo = next(s for s in senior if s.category == "algorithms")
    assert senior_algo.n_questions >= 2


def test_plan_adds_applied_ai_shard_for_applied_ai_position():
    shards, _ = plan_for_resume(
        parsed={}, claim_mappings=[], position="applied_ai", level="senior"
    )
    cats = [s.category for s in shards]
    assert "applied_ai_specific" in cats


def test_plan_dedupes_claim_text_across_mapped_and_unmapped():
    text = "Same claim text"
    mappings = [_MockMapping(claim=text, project_id=None)]
    parsed = {
        "skills": [],
        "claims": [{"text": text, "section": "experience"}],
    }
    shards, _ = plan_for_resume(
        parsed=parsed, claim_mappings=mappings, position="swe_generic", level="mid"
    )
    claim_shards = [s for s in shards if s.category == "experience_claim"]
    assert len(claim_shards) == 1


def test_plan_caps_claim_shards():
    # 20 mapped claims should not produce 20 shards.
    mappings = [
        _MockMapping(claim=f"Claim {i}", project_id=None) for i in range(20)
    ]
    shards, _ = plan_for_resume(
        parsed={}, claim_mappings=mappings, position="swe_generic", level="mid",
        max_claim_shards=4,
    )
    claim_shards = [s for s in shards if s.category == "experience_claim"]
    assert len(claim_shards) == 4
