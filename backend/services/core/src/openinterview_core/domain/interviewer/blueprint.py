from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...infra.db.common_kb_repository import SqlCommonKBRepository


DEFAULT_WEIGHTS = {
    "experience_claim": 1.3,
    "project_overview": 1.1,
    "algorithms": 1.0,
    "data_structures": 0.9,
    "system_design": 1.0,
    "architecture": 1.0,
    "applied_ai_specific": 0.8,
    "behavioral_grounded": 0.7,
    "company_experience": 0.6,
    "language": 0.5,
}


@dataclass(frozen=True)
class InterviewBlueprint:
    category_weights: dict[str, float] = field(default_factory=dict)
    languages: list[str] = field(default_factory=list)
    target_company: str | None = None
    include_company_style: bool = True
    notes: list[str] = field(default_factory=list)
    n_questions: int = 5

    def model_dump(self) -> dict:
        return {
            "category_weights": self.category_weights,
            "languages": self.languages,
            "target_company": self.target_company,
            "include_company_style": self.include_company_style,
            "notes": self.notes,
            "n_questions": self.n_questions,
        }


class InterviewBlueprintService:
    def __init__(self, *, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def build(
        self,
        *,
        user_id: UUID,
        position: str,
        level: str,
        n_questions: int,
        target_company: str | None = None,
        session_preferences: dict | None = None,
    ) -> InterviewBlueprint:
        weights = _defaults_for(position=position, level=level)
        languages: list[str] = []
        notes: list[str] = []
        include_company_style = True

        async with self._sm() as s:
            repo = SqlCommonKBRepository(s)
            saved = await repo.get_user_preferences(user_id=user_id)
            company_name = target_company or (saved.target_company if saved else None)
            if saved and saved.category_weights:
                weights.update(_numeric_map(saved.category_weights))
                notes.append("using saved user interview category preferences")
            if saved and saved.languages:
                languages = [str(x) for x in saved.languages if str(x).strip()]
            if saved:
                include_company_style = bool(saved.include_company_style)

            pref = session_preferences or {}
            if pref.get("category_weights"):
                weights.update(_numeric_map(pref.get("category_weights") or {}))
                notes.append("using session category preferences")
            if pref.get("languages"):
                languages = [str(x) for x in pref.get("languages") or [] if str(x).strip()]
            if "include_company_style" in pref:
                include_company_style = bool(pref["include_company_style"])

            if company_name and include_company_style:
                profile = await repo.get_company_profile(company_name)
                if profile and profile.category_weights:
                    for k, v in _numeric_map(profile.category_weights).items():
                        weights[k] = max(weights.get(k, 0.0), v * 2.0)
                    if not languages and profile.language_preferences:
                        languages = [str(x) for x in profile.language_preferences if str(x).strip()]
                    notes.append(f"using company profile for {profile.company}")

        return InterviewBlueprint(
            category_weights=_normalize_weights(weights),
            languages=languages[:5],
            target_company=target_company or company_name,
            include_company_style=include_company_style,
            notes=notes,
            n_questions=max(1, min(20, int(n_questions or 5))),
        )


def _defaults_for(*, position: str, level: str) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    if position == "applied_ai":
        weights["applied_ai_specific"] = 1.5
        weights["ai_design"] = 1.4
        weights["system_design"] = 1.2
    if level in {"senior", "staff", "principal", "tech_lead"}:
        weights["system_design"] += 0.4
        weights["architecture"] += 0.4
        weights["behavioral_grounded"] += 0.2
    if level in {"junior", "mid"}:
        weights["algorithms"] += 0.4
        weights["data_structures"] += 0.3
        weights["language"] += 0.2
    return weights


def _numeric_map(raw: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = max(0.0, float(v))
        except (TypeError, ValueError):
            continue
    return out


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    vals = {k: max(0.0, float(v)) for k, v in weights.items()}
    max_v = max(vals.values() or [1.0])
    if max_v <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: round(v / max_v, 3) for k, v in vals.items()}
