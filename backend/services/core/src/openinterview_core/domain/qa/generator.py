"""ShardGenerator: retrieves project context for a shard and asks LLM to produce
grounded interview questions with ideal answers and evidence references."""
from __future__ import annotations

import json
from uuid import UUID

from openinterview_schemas import ChatMessage

from .types import QAEvidence, QAItem, QAShard


class ShardGenerator:
    def __init__(
        self,
        *,
        gateway,
        embedder,
        vector_store,
        collection: str,
        logical_model: str = "chat-strong",
        retrieval_k: int = 8,
    ) -> None:
        self._gw = gateway
        self._embed = embedder
        self._vs = vector_store
        self._coll = collection
        self._model = logical_model
        self._k = retrieval_k

    async def generate(
        self,
        *,
        user_id: UUID,
        project_name: str,
        project_summary: str | None,
        shard: QAShard,
        level: str,
    ) -> list[QAItem]:
        vectors = await self._embed.embed(user_id=user_id, texts=[shard.retrieval_query])
        if not vectors:
            return []
        matches = await self._vs.query(
            collection=self._coll, embedding=vectors[0], k=self._k
        )

        evidence_blocks: list[str] = []
        evidence_meta: list[QAEvidence] = []
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
                QAEvidence(rel_path=rel, start_line=start, end_line=end, snippet=snippet)
            )

        prompt = self._build_prompt(
            project_name=project_name,
            project_summary=project_summary,
            shard=shard,
            level=level,
            evidence_blocks=evidence_blocks,
        )

        r = await self._gw.chat(
            user_id=user_id,
            logical_model=self._model,
            messages=[ChatMessage(role="user", content=prompt)],
        )
        data = _safe_json(r.content, default={})
        items_raw = data.get("items") or []
        out: list[QAItem] = []
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            q = str(it.get("question") or "").strip()
            a = str(it.get("ideal_answer") or "").strip()
            if not q or not a:
                continue
            # Resolve evidence indices the LLM cited.
            ev_idxs = it.get("evidence_indices") or []
            evidence: list[QAEvidence] = []
            for idx in ev_idxs:
                if isinstance(idx, int) and 0 <= idx < len(evidence_meta):
                    evidence.append(evidence_meta[idx])
            difficulty = int(it.get("difficulty") or 3)
            difficulty = max(1, min(5, difficulty))
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
                )
            )
        return out

    def _build_prompt(
        self,
        *,
        project_name: str,
        project_summary: str | None,
        shard: QAShard,
        level: str,
        evidence_blocks: list[str],
    ) -> str:
        ev = "\n".join(
            f"[{i}] {b}" for i, b in enumerate(evidence_blocks)
        ) or "(no evidence available)"
        return (
            "You are an expert interviewer. Generate interview questions tied to a "
            "candidate's actual project. Use the evidence to ground each question.\n\n"
            f"PROJECT: {project_name}\n"
            f"PROJECT SUMMARY: {(project_summary or '')[:1500]}\n"
            f"CATEGORY: {shard.category}\n"
            f"FOCUS: {shard.focus}\n"
            f"LEVEL: {level}  (junior/mid/senior/tech_lead -- escalate depth)\n"
            f"NUMBER OF QUESTIONS: {shard.n_questions}\n\n"
            "EVIDENCE BLOCKS (cite by index in evidence_indices):\n"
            f"{ev}\n\n"
            "Return STRICT JSON:\n"
            '{ "items": [ { "question": str, "ideal_answer": str, '
            '"evidence_indices": [int], "difficulty": 1-5, "tags": [str] } ] }\n'
            "Rules:\n"
            "- Each question must be answerable using the evidence (or general principles applied to it).\n"
            "- Ideal answer must be concrete and reference specifics from the project where relevant.\n"
            "- difficulty: 1=intro, 5=expert. Match the LEVEL.\n"
            "- For 'behavioral_grounded' or when no evidence applies, evidence_indices may be [].\n"
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
