"""ResumeShardGenerator: produce QA items from a resume shard.

For ``experience_claim`` shards with a linked project, we pull short evidence
snippets from the project's vector store (same path the project generator uses)
so the question can cite a file. Otherwise we go LLM-only on the claim text.
"""
from __future__ import annotations

import json
from uuid import UUID

from openinterview_schemas import ChatMessage

from ...infra.vector import vector_collection_for_user_project
from .resume_planner import ResumeShardContext
from .types import QAEvidence, QAItem, QAShard


class ResumeShardGenerator:
    def __init__(
        self,
        *,
        gateway,
        embedder,
        vector_store,
        logical_model: str = "chat-strong",
        retrieval_k: int = 4,
    ) -> None:
        self._gw = gateway
        self._embed = embedder
        self._vs = vector_store
        self._model = logical_model
        self._k = retrieval_k

    async def generate(
        self,
        *,
        user_id: UUID,
        shard: QAShard,
        context: ResumeShardContext,
        level: str,
        candidate_name: str | None,
    ) -> list[QAItem]:
        evidence_meta: list[QAEvidence] = []
        evidence_blocks: list[str] = []

        # Pull project-grounded evidence for claim-shards that have a linked
        # project. We use the same per-user/project collection the project
        # generator writes to.
        if (
            context.category == "experience_claim"
            and context.source_project_id
            and context.claim
        ):
            try:
                vectors = await self._embed.embed(
                    user_id=user_id, texts=[context.claim]
                )
                if vectors:
                    coll = vector_collection_for_user_project(
                        str(user_id), context.source_project_id
                    )
                    matches = await self._vs.query(
                        collection=coll, embedding=vectors[0], k=self._k
                    )
                    for m in matches:
                        md = m.metadata or {}
                        rel = str(md.get("rel_path") or "")
                        start = int(md.get("start_line") or 0)
                        end = int(md.get("end_line") or 0)
                        snippet = m.text[:600]
                        evidence_blocks.append(
                            f"FILE {rel}:{start}-{end}\n{snippet}\n---"
                        )
                        evidence_meta.append(
                            QAEvidence(
                                rel_path=rel,
                                start_line=start,
                                end_line=end,
                                snippet=snippet,
                            )
                        )
            except Exception:
                # Non-fatal: fall back to non-grounded generation.
                evidence_blocks = []
                evidence_meta = []

        prompt = self._build_prompt(
            shard=shard,
            context=context,
            level=level,
            candidate_name=candidate_name,
            evidence_blocks=evidence_blocks,
        )

        r = await self._gw.chat(
            user_id=user_id,
            logical_model=self._model,
            messages=[ChatMessage(role="user", content=prompt)],
        )
        data = _safe_json(r.content, default={})
        items_raw = data.get("items") or []

        meta = {
            "claim": context.claim,
            "claim_section": context.claim_section,
            "source_project_id": context.source_project_id,
        }
        # Drop empty fields so meta is null when nothing useful is in it.
        meta = {k: v for k, v in meta.items() if v}

        out: list[QAItem] = []
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            q = str(it.get("question") or "").strip()
            a = str(it.get("ideal_answer") or "").strip()
            if not q or not a:
                continue
            ev_idxs = it.get("evidence_indices") or []
            evidence: list[QAEvidence] = []
            for idx in ev_idxs:
                if isinstance(idx, int) and 0 <= idx < len(evidence_meta):
                    evidence.append(evidence_meta[idx])
            difficulty = max(1, min(5, int(it.get("difficulty") or 3)))
            tags = [str(t) for t in (it.get("tags") or [])][:6]
            out.append(
                QAItem(
                    category=shard.category,
                    level=level,
                    question=q,
                    ideal_answer=a,
                    evidence=evidence,
                    difficulty=difficulty,
                    tags=tags,
                    meta=meta or None,
                )
            )
        return out

    def _build_prompt(
        self,
        *,
        shard: QAShard,
        context: ResumeShardContext,
        level: str,
        candidate_name: str | None,
        evidence_blocks: list[str],
    ) -> str:
        ev = (
            "\n".join(f"[{i}] {b}" for i, b in enumerate(evidence_blocks))
            or "(no project evidence available — write a behavioral question)"
        )
        candidate = candidate_name or "the candidate"
        extra = context.extra or {}

        candidate_context = (
            f"BACKGROUND: {extra.get('title','')} at {extra.get('company','')}\n"
            if extra.get("title") or extra.get("company")
            else ""
        )
        skill_line = (
            "RELEVANT SKILLS: " + ", ".join(extra.get("skills") or []) + "\n"
            if extra.get("skills")
            else ""
        )

        if shard.category == "experience_claim":
            grounding_hint = (
                "If evidence blocks are present, ASK the candidate to walk "
                "through the actual implementation cited there; cite the file "
                "in evidence_indices."
                if evidence_blocks
                else "No file evidence — ask the candidate to describe the "
                "design and trade-offs they made."
            )
            scope = (
                f"CLAIM (from candidate's resume): {context.claim}\n"
                f"SECTION: {context.claim_section or 'experience'}\n"
            )
        elif shard.category == "skills_breadth":
            scope = (
                "CANDIDATE'S LISTED SKILLS:\n- "
                + "\n- ".join(extra.get("skills") or [])
                + "\n"
            )
            grounding_hint = (
                "Pick ONE skill that's hardest to fake; ask for a concrete "
                "example of using it (specific project, specific decision)."
            )
        elif shard.category == "project_overview":
            scope = (
                f"RESUME PROJECT: {extra.get('project_name','')}\n"
                f"SUMMARY: {extra.get('project_summary','')[:1500]}\n"
            )
            grounding_hint = (
                "Ask about an architecturally interesting decision in this "
                "project. Avoid yes/no questions."
            )
        elif shard.category == "system_design":
            scope = candidate_context + skill_line
            grounding_hint = (
                "Pose ONE realistic system-design problem the candidate would "
                "plausibly have encountered given the BACKGROUND / SKILLS "
                "above (e.g. a backend SWE working on payments → design an "
                "idempotent retry layer; an applied-AI engineer → design a "
                "near-real-time embedding refresh pipeline). Ask the "
                "candidate to walk through scope, data model, scale "
                "estimates, and trade-offs. The 'ideal_answer' should be a "
                "rubric of what a strong response covers, not a full design."
            )
        elif shard.category == "architecture":
            scope = candidate_context + skill_line
            grounding_hint = (
                "Probe architectural reasoning: component boundaries, "
                "consistency vs availability, sync vs async, batch vs stream, "
                "deploy/rollback strategy. Pick one tension the candidate "
                "would have hit; have them justify a concrete choice."
            )
        elif shard.category == "algorithms":
            scope = candidate_context + skill_line
            level_hint = {
                "junior": "Classical DSA: arrays, hashmaps, simple recursion. "
                "Probe correctness + Big-O.",
                "mid": "Mid-difficulty DSA: graphs, two-pointer, dynamic "
                "programming. Push for cleaner Big-O.",
                "senior": "Harder asymptotic / concurrency reasoning, "
                "amortised analysis, or non-trivial optimisations. Avoid "
                "rote Leetcode.",
                "tech_lead": "Pick a system-y algorithmic scenario "
                "(e.g. consistent hashing, bloom filter sizing). Probe "
                "trade-offs + when *not* to use a clever data structure.",
                "lead": "Pick a system-y algorithmic scenario. Probe "
                "trade-offs + when *not* to use a clever data structure.",
            }.get(level, "Mid-difficulty DSA. Push for cleaner Big-O.")
            grounding_hint = (
                "Pose ONE algorithmic scenario described in plain English "
                "(not boilerplate Leetcode framing). "
                f"{level_hint} The 'ideal_answer' is a rubric of what a "
                "strong response covers (approach, complexity, edge cases)."
            )
        elif shard.category == "applied_ai_specific":
            scope = candidate_context + skill_line
            grounding_hint = (
                "Pick ONE applied-AI failure mode (drift, eval regression, "
                "prompt injection, retrieval recall vs cost, etc.) and ask "
                "how the candidate would detect / mitigate it in their stack."
            )
        else:  # behavioral_grounded
            scope = (
                f"ROLE CONTEXT: {extra.get('title','')} at {extra.get('company','')}\n"
                f"BULLET: {context.claim or ''}\n"
            )
            grounding_hint = (
                "Behavioral question (STAR format) grounded in this bullet. "
                "Ask for specifics: what they personally owned, what failed, "
                "what changed afterwards."
            )

        return (
            "You are an expert interviewer building ONE high-signal interview "
            f"question from {candidate}'s resume.\n\n"
            f"{scope}\n"
            f"CATEGORY: {shard.category}\n"
            f"FOCUS: {shard.focus}\n"
            f"LEVEL: {level}  (junior/mid/senior/tech_lead -- escalate depth)\n"
            f"NUMBER OF QUESTIONS: {shard.n_questions}\n"
            f"GROUNDING: {grounding_hint}\n\n"
            "EVIDENCE BLOCKS (cite by index in evidence_indices when relevant):\n"
            f"{ev}\n\n"
            "Return STRICT JSON:\n"
            '{ "items": [ { "question": str, "ideal_answer": str, '
            '"evidence_indices": [int], "difficulty": 1-5, "tags": [str] } ] }\n'
            "Rules:\n"
            "- Each question must reference SPECIFIC content from the resume.\n"
            "- Ideal answer must be concrete (1-3 sentences, mention what a "
            "strong answer covers).\n"
            "- difficulty: 1=intro, 5=expert. Match the LEVEL.\n"
            "- For shards without evidence, leave evidence_indices = [].\n"
            "- JSON only, no prose."
        )


def _safe_json(text: str, *, default):
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        return json.loads(cleaned)
    except Exception:
        return default
