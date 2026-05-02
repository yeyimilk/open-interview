"""ResumeQAPlanner: turn a parsed resume + claim mappings into shards.

Each shard targets one of:
- ``experience_claim`` — a single concrete claim (preferably one mapped to a
  project so we can ground the question in code).
- ``skills_breadth`` — listed skills the candidate didn't tie to a specific
  achievement; one shard, multiple questions.
- ``project_overview`` — one shard per resume-listed project that has a summary.
- ``behavioral_grounded`` — pulled from the leading bullet of each top
  experience entry.

Unlike the project planner, this one is fully deterministic: we already have
the resume's own structured data; the LLM doesn't need to refine focus.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import QAShard


@dataclass
class ResumeShardContext:
    """Carries the per-shard payload the generator needs to write a question.

    Stored on a side-channel keyed by the shard's ``retrieval_query`` so we
    don't have to widen ``QAShard`` itself."""

    category: str
    claim: str | None = None
    claim_section: str | None = None
    source_project_id: str | None = None
    grounding: list[dict] | None = None
    extra: dict[str, Any] | None = None


_LEVEL_ORDER = {"junior": 1, "mid": 2, "senior": 3, "tech_lead": 4, "lead": 4}


def _level_at_least(level: str, threshold: str) -> bool:
    return _LEVEL_ORDER.get(level, 2) >= _LEVEL_ORDER.get(threshold, 2)


def plan_for_resume(
    *,
    parsed: dict,
    claim_mappings: list,
    position: str,
    level: str,
    max_claim_shards: int = 6,
) -> tuple[list[QAShard], dict[str, ResumeShardContext]]:
    """Build shards. Returns ``(shards, context_by_query)``.

    The generator looks up its per-shard context by ``shard.retrieval_query``,
    which is also a unique key in the context map.
    """
    shards: list[QAShard] = []
    ctx: dict[str, ResumeShardContext] = {}

    # 1) Best-grounded claims first. Mappings with confidence >= 50 are the
    # ones we trust enough to point to a specific project; the rest still
    # become shards but without a project reference.
    sorted_mappings = sorted(
        list(claim_mappings or []),
        key=lambda m: (-(getattr(m, "confidence", 0) or 0)),
    )
    seen_claims: set[str] = set()
    for i, m in enumerate(sorted_mappings[: max_claim_shards * 2]):
        text = (getattr(m, "claim", None) or "").strip()
        if not text or text in seen_claims:
            continue
        seen_claims.add(text)
        rq = f"resume_claim::{i}::{text[:40]}"
        shards.append(
            QAShard(
                category="experience_claim",
                focus=f"Probe the candidate's claim: {text}",
                n_questions=1,
                retrieval_query=rq,
            )
        )
        ctx[rq] = ResumeShardContext(
            category="experience_claim",
            claim=text,
            claim_section="experience",
            source_project_id=(
                str(getattr(m, "project_id", None))
                if getattr(m, "project_id", None) is not None
                else None
            ),
            grounding=getattr(m, "grounding", None) or None,
        )
        if len([s for s in shards if s.category == "experience_claim"]) >= max_claim_shards:
            break

    # 2) Pull additional claims directly from `parsed.claims` that the mapper
    # didn't surface (e.g. unmapped ones). Each gets a non-grounded shard.
    extra_claims = parsed.get("claims") or []
    for i, c in enumerate(extra_claims):
        if len([s for s in shards if s.category == "experience_claim"]) >= max_claim_shards:
            break
        text = ""
        section = None
        if isinstance(c, dict):
            text = str(c.get("text") or c.get("claim") or "").strip()
            section = c.get("section") or None
        elif isinstance(c, str):
            text = c.strip()
        if not text or text in seen_claims:
            continue
        seen_claims.add(text)
        rq = f"resume_claim_extra::{i}::{text[:40]}"
        shards.append(
            QAShard(
                category="experience_claim",
                focus=f"Probe the candidate's claim: {text}",
                n_questions=1,
                retrieval_query=rq,
            )
        )
        ctx[rq] = ResumeShardContext(
            category="experience_claim",
            claim=text,
            claim_section=str(section) if section else "experience",
            source_project_id=None,
        )

    # 3) Skills breadth — one shard with multiple questions.
    skills = [str(s) for s in (parsed.get("skills") or []) if s]
    if skills:
        rq = "resume_skills_breadth"
        shards.append(
            QAShard(
                category="skills_breadth",
                focus=(
                    "Probe breadth across the candidate's listed skills. Pick a "
                    "skill, ask for a concrete example of using it."
                ),
                n_questions=2,
                retrieval_query=rq,
            )
        )
        ctx[rq] = ResumeShardContext(
            category="skills_breadth",
            extra={"skills": skills[:25]},
        )

    # 4) One shard per resume-listed project (limited to 3 to keep the bank
    # focused).
    for i, p in enumerate((parsed.get("projects") or [])[:3]):
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or f"project {i+1}")
        summary = str(p.get("summary") or "")
        if not summary:
            continue
        rq = f"resume_project::{i}::{name[:40]}"
        shards.append(
            QAShard(
                category="project_overview",
                focus=f"Architecture & trade-offs for the resume project: {name}",
                n_questions=1,
                retrieval_query=rq,
            )
        )
        ctx[rq] = ResumeShardContext(
            category="project_overview",
            extra={"project_name": name, "project_summary": summary},
        )

    # 5) Behavioral — one bullet from each top-3 experience entry.
    for i, exp in enumerate((parsed.get("experience") or [])[:3]):
        if not isinstance(exp, dict):
            continue
        bullets = exp.get("bullets") or []
        bullet = next((str(b) for b in bullets if isinstance(b, str) and b.strip()), "")
        if not bullet:
            continue
        title = str(exp.get("title") or "")
        company = str(exp.get("company") or "")
        rq = f"resume_behavioral::{i}::{title[:30]}"
        shards.append(
            QAShard(
                category="behavioral_grounded",
                focus=(
                    f"Behavioral question grounded in the candidate's role at "
                    f"{company} ({title}). Bullet: {bullet}"
                ),
                n_questions=1,
                retrieval_query=rq,
            )
        )
        ctx[rq] = ResumeShardContext(
            category="behavioral_grounded",
            claim=bullet,
            claim_section="experience",
            extra={"title": title, "company": company},
        )

    # 6) Generalist core that mirrors what a real interviewer would cover —
    # independent of how rich the resume is. The candidate's most-recent
    # title/skills are passed as flavour so questions are tailored, but they
    # don't depend on claim mappings.
    most_recent_title = ""
    most_recent_company = ""
    exp = parsed.get("experience") or []
    if exp and isinstance(exp[0], dict):
        most_recent_title = str(exp[0].get("title") or "")
        most_recent_company = str(exp[0].get("company") or "")
    skills = [str(s) for s in (parsed.get("skills") or []) if s]

    flavour = {
        "title": most_recent_title,
        "company": most_recent_company,
        "skills": skills[:25],
        "position": position,
        "level": level,
    }

    # System design — every level gets at least one; mid+ gets two.
    sd_qs = 2 if _level_at_least(level, "mid") else 1
    rq = "resume_system_design"
    shards.append(
        QAShard(
            category="system_design",
            focus=(
                "End-to-end system design relevant to the candidate's "
                "background. Pick a problem space the candidate's resume "
                "suggests they have context for."
            ),
            n_questions=sd_qs,
            retrieval_query=rq,
        )
    )
    ctx[rq] = ResumeShardContext(category="system_design", extra=flavour)

    # Architecture / trade-offs — emphasized for mid+.
    if _level_at_least(level, "mid"):
        rq = "resume_architecture"
        shards.append(
            QAShard(
                category="architecture",
                focus=(
                    "Component boundaries, dependencies, deployment, "
                    "consistency vs availability trade-offs the candidate "
                    "would have hit in their listed roles."
                ),
                n_questions=2 if _level_at_least(level, "senior") else 1,
                retrieval_query=rq,
            )
        )
        ctx[rq] = ResumeShardContext(category="architecture", extra=flavour)

    # Algorithms / data structures — junior/mid get one, senior+ get two.
    # Applied-AI roles also get an algorithms shard, but biased toward
    # streaming / online compute rather than classical Leetcode.
    algo_qs = 2 if _level_at_least(level, "senior") else 1
    rq = "resume_algorithms"
    shards.append(
        QAShard(
            category="algorithms",
            focus=(
                "Coding / data-structures depth appropriate for the level. "
                "For junior/mid, classical DSA. For senior+, harder asymptotic "
                "or concurrency reasoning. Not a Leetcode dump — pick one "
                "scenario and probe it deeply."
            ),
            n_questions=algo_qs,
            retrieval_query=rq,
        )
    )
    ctx[rq] = ResumeShardContext(category="algorithms", extra=flavour)

    # Applied-AI extras (matches the project planner's beef-up).
    if position == "applied_ai":
        rq = "resume_applied_ai"
        shards.append(
            QAShard(
                category="applied_ai_specific",
                focus=(
                    "Prompts, retrieval design, evaluation/regression, "
                    "cost & latency, drift detection, safety — anchored in "
                    "the candidate's listed AI work."
                ),
                n_questions=2,
                retrieval_query=rq,
            )
        )
        ctx[rq] = ResumeShardContext(category="applied_ai_specific", extra=flavour)

    # If we somehow ended up with nothing (e.g. brand new empty resume), at
    # least emit a generic skills shard so the bank isn't empty.
    if not shards:
        rq = "resume_fallback_generic"
        shards.append(
            QAShard(
                category="behavioral_grounded",
                focus="Open-ended walkthrough of the candidate's most recent role.",
                n_questions=2,
                retrieval_query=rq,
            )
        )
        ctx[rq] = ResumeShardContext(category="behavioral_grounded")

    return shards, ctx
