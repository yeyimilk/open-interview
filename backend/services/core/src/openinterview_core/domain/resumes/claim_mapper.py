"""Claim ↔ project-fact grounding.

Given a claim and the user's project KB (vector store), retrieve top-k
relevant code/doc chunks and ask the LLM to produce a grounding decision.
"""
from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

from openinterview_schemas import (
    ChatMessage,
    RetrieveRequest,
    RetrievalPurpose,
    RetrievalSource,
)

from ..retrieval import RetrievalService
from .types import Claim, ResumeClaimMapping


class ClaimMapper(Protocol):
    async def map(
        self,
        *,
        user_id: UUID,
        claims: list[Claim],
        project_ids: list[UUID],
    ) -> list[ResumeClaimMapping]: ...


class LLMClaimMapper(ClaimMapper):
    def __init__(
        self,
        *,
        gateway,
        retrieval_service: RetrievalService,
        logical_model: str = "chat-fast",
        k: int = 6,
    ) -> None:
        self._gw = gateway
        self._retrieval = retrieval_service
        self._model = logical_model
        self._k = k

    async def map(self, *, user_id, claims, project_ids):  # type: ignore[override]
        if not claims or not project_ids:
            return []

        out: list[ResumeClaimMapping] = []
        for claim in claims:
            best_evidence: list[dict] = []
            best_pid: str | None = None
            retrieved = await self._retrieval.retrieve(
                RetrieveRequest(
                    user_id=user_id,
                    query=claim.text,
                    purpose=RetrievalPurpose.claim_mapping,
                    sources=[RetrievalSource.project],
                    project_ids=project_ids,
                    top_k=max(self._k * max(1, len(project_ids)), self._k),
                    per_source_top_k={"project": self._k},
                    context_char_budget=6000,
                )
            )
            by_project: dict[str, list] = {}
            for chunk in retrieved.chunks:
                pid = chunk.citation.project_id
                if pid is None:
                    continue
                by_project.setdefault(str(pid), []).append(chunk)
            for pid, chunks in by_project.items():
                chunks.sort(key=lambda c: c.score, reverse=True)
                if chunks and (
                    not best_evidence or chunks[0].score > best_evidence[0].get("score", 0)
                ):
                    best_pid = pid
                    best_evidence = [
                        {
                            "rel_path": c.citation.rel_path or "",
                            "start_line": c.citation.start_line,
                            "end_line": c.citation.end_line,
                            "score": c.score,
                            "snippet": c.text[:600],
                        }
                        for c in chunks[: self._k]
                    ]
            confidence = await self._judge(user_id, claim.text, best_evidence)
            out.append(
                ResumeClaimMapping(
                    claim=claim.text,
                    project_id=best_pid,
                    grounding=best_evidence,
                    confidence=confidence,
                    section=claim.section,
                    category=claim.category,
                )
            )
        return out

    async def _judge(self, user_id: UUID, claim: str, evidence: list[dict]) -> int:
        if not evidence:
            return 0
        prompt = (
            "On a scale 0-100, how strongly does the EVIDENCE support the CLAIM? "
            "Reply with JSON: {\"confidence\": <int 0-100>}.\n"
            f"CLAIM: {claim}\n"
            f"EVIDENCE: {json.dumps(evidence)[:6000]}"
        )
        try:
            r = await self._gw.chat(
                user_id=user_id,
                logical_model=self._model,
                messages=[ChatMessage(role="user", content=prompt)],
            )
            data = json.loads(r.content.strip().strip("`"))
            return max(0, min(100, int(data.get("confidence", 0))))
        except Exception:
            return 0
