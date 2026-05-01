"""Claim ↔ project-fact grounding.

Given a claim and the user's project KB (vector store), retrieve top-k
relevant code/doc chunks and ask the LLM to produce a grounding decision.
"""
from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

from openinterview_schemas import ChatMessage

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
        embedder,
        vector_store,
        collection_for_project: callable,  # type: ignore[type-arg]
        logical_model: str = "chat-fast",
        k: int = 6,
    ) -> None:
        self._gw = gateway
        self._embedder = embedder
        self._vec = vector_store
        self._coll_fn = collection_for_project
        self._model = logical_model
        self._k = k

    async def map(self, *, user_id, claims, project_ids):  # type: ignore[override]
        if not claims or not project_ids:
            return []

        # Embed all claim texts in one call.
        embeddings = await self._embedder.embed(
            user_id=user_id, texts=[c.text for c in claims]
        )

        out: list[ResumeClaimMapping] = []
        for claim, vec in zip(claims, embeddings, strict=True):
            best_evidence: list[dict] = []
            best_pid: str | None = None
            for pid in project_ids:
                coll = self._coll_fn(str(user_id), str(pid))
                matches = await self._vec.query(collection=coll, embedding=vec, k=self._k)
                if matches:
                    if not best_evidence or matches[0].score > best_evidence[0].get("score", 0):
                        best_pid = str(pid)
                        best_evidence = [
                            {
                                "rel_path": m.metadata.get("rel_path", ""),
                                "start_line": m.metadata.get("start_line"),
                                "end_line": m.metadata.get("end_line"),
                                "score": m.score,
                                "snippet": m.text[:600],
                            }
                            for m in matches
                        ]
            confidence = await self._judge(user_id, claim.text, best_evidence)
            out.append(
                ResumeClaimMapping(
                    claim=claim.text,
                    project_id=best_pid,
                    grounding=best_evidence,
                    confidence=confidence,
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
