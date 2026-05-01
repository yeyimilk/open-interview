"""QA Planner: turns project summary + architecture into shards (categories)."""
from __future__ import annotations

import json
from uuid import UUID

from openinterview_schemas import ChatMessage

from .types import QAShard

DEFAULT_CATEGORIES = [
    ("architecture", "Component boundaries, dependencies, deployment", 4),
    ("code_quality", "Readability, testability, edge cases", 3),
    ("data_modeling", "Schemas, indexes, consistency, migrations", 3),
    ("scaling", "Bottlenecks, caching, async, horizontal scaling", 3),
    ("testing", "Test strategy, coverage, hardest bugs encountered", 2),
    ("applied_ai_specific", "Prompts, retrieval, evals, costs, drift", 4),
    ("behavioral_grounded", "Behavioral questions tied to concrete code/decisions", 3),
]


class QAPlanner:
    """Deterministic by default; if `use_llm=True`, ask LLM to refine focus per shard."""

    def __init__(self, gateway=None, logical_model: str = "chat-strong") -> None:
        self._gw = gateway
        self._model = logical_model

    async def plan(
        self,
        *,
        user_id: UUID,
        project_name: str,
        project_summary: str | None,
        architecture: dict | None,
        position: str,
        level: str,
    ) -> list[QAShard]:
        # Baseline shards from defaults.
        shards = [
            QAShard(
                category=cat,
                focus=focus,
                n_questions=n,
                retrieval_query=f"{project_name} {cat} {level}",
            )
            for cat, focus, n in DEFAULT_CATEGORIES
        ]
        # If applied-AI position, beef up the AI shard.
        if position == "applied_ai":
            for s in shards:
                if s.category == "applied_ai_specific":
                    s.n_questions = 6
                if s.category == "scaling":
                    s.focus = "Token budgets, caching, batch vs stream, GPU/CPU mix"

        if self._gw is None:
            return shards

        # Optional: ask LLM to refine each shard's focus given project context.
        try:
            prompt = (
                "You are designing an interview question plan. For each category below, "
                "rewrite the 'focus' to be specific to THIS project. Return strict JSON: "
                '{"shards": [{"category": str, "focus": str, "retrieval_query": str}]}.\n\n'
                f"PROJECT: {project_name}\nLEVEL: {level}\nPOSITION: {position}\n"
                f"SUMMARY:\n{(project_summary or '')[:1500]}\n\n"
                f"ARCH JSON:\n{json.dumps(architecture or {})[:1500]}\n\n"
                f"CATEGORIES: {[s.category for s in shards]}"
            )
            r = await self._gw.chat(
                user_id=user_id,
                logical_model=self._model,
                messages=[ChatMessage(role="user", content=prompt)],
            )
            data = _safe_json(r.content, default={})
            for refined in data.get("shards", []):
                cat = refined.get("category")
                for s in shards:
                    if s.category == cat:
                        if refined.get("focus"):
                            s.focus = str(refined["focus"])[:500]
                        if refined.get("retrieval_query"):
                            s.retrieval_query = str(refined["retrieval_query"])[:300]
        except Exception:
            pass
        return shards


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
