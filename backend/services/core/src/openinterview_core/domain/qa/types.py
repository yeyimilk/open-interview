from __future__ import annotations

from dataclasses import dataclass, field

CANONICAL_FOLLOW_UP_AXES: tuple[str, ...] = (
    "implementation_details",
    "trade_offs",
    "scale",
    "debugging",
    "ownership",
    "failure_modes",
    "metrics",
    "testing",
    "alternatives",
    "reflection",
)

_AXIS_ALIASES = {
    "implementation": "implementation_details",
    "implementation detail": "implementation_details",
    "implementation details": "implementation_details",
    "details": "implementation_details",
    "tradeoff": "trade_offs",
    "tradeoffs": "trade_offs",
    "trade offs": "trade_offs",
    "trade-offs": "trade_offs",
    "scaling": "scale",
    "debug": "debugging",
    "bugs": "debugging",
    "bug": "debugging",
    "failure mode": "failure_modes",
    "failure modes": "failure_modes",
    "failures": "failure_modes",
    "measurement": "metrics",
    "measurements": "metrics",
    "test": "testing",
    "tests": "testing",
    "alternative": "alternatives",
    "ownership": "ownership",
    "reflection": "reflection",
}

_CATEGORY_AXIS_DEFAULTS: dict[str, list[str]] = {
    "experience_claim": [
        "ownership",
        "implementation_details",
        "trade_offs",
        "metrics",
        "failure_modes",
    ],
    "project_overview": [
        "implementation_details",
        "trade_offs",
        "scale",
        "failure_modes",
        "alternatives",
    ],
    "architecture": [
        "trade_offs",
        "scale",
        "failure_modes",
        "alternatives",
        "testing",
    ],
    "system_design": [
        "scale",
        "trade_offs",
        "failure_modes",
        "metrics",
        "alternatives",
    ],
    "algorithms": [
        "implementation_details",
        "testing",
        "scale",
        "alternatives",
        "debugging",
    ],
    "code_quality": [
        "implementation_details",
        "testing",
        "debugging",
        "trade_offs",
        "alternatives",
    ],
    "data_modeling": [
        "trade_offs",
        "scale",
        "failure_modes",
        "testing",
        "alternatives",
    ],
    "scaling": [
        "scale",
        "metrics",
        "failure_modes",
        "trade_offs",
        "debugging",
    ],
    "testing": [
        "testing",
        "failure_modes",
        "debugging",
        "metrics",
        "alternatives",
    ],
    "applied_ai_specific": [
        "metrics",
        "failure_modes",
        "debugging",
        "trade_offs",
        "scale",
    ],
    "behavioral_grounded": [
        "ownership",
        "reflection",
        "trade_offs",
        "failure_modes",
        "metrics",
    ],
}


def normalize_follow_up_axes(raw, *, category: str | None = None) -> list[str]:
    """Return canonical follow-up axes, with category defaults as fallback."""
    out: list[str] = []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = raw
    else:
        values = []

    canonical = set(CANONICAL_FOLLOW_UP_AXES)
    for v in values:
        if not isinstance(v, str):
            continue
        key = v.strip().lower().replace("-", "_").replace(" ", "_")
        key = _AXIS_ALIASES.get(v.strip().lower(), key)
        if key in canonical and key not in out:
            out.append(key)
        if len(out) >= 5:
            return out

    if out:
        return out

    defaults = _CATEGORY_AXIS_DEFAULTS.get(str(category or "").lower())
    return list(defaults or [
        "implementation_details",
        "trade_offs",
        "failure_modes",
        "testing",
        "reflection",
    ])[:5]


@dataclass(frozen=True)
class QAEvidence:
    rel_path: str
    start_line: int = 0
    end_line: int = 0
    snippet: str = ""


@dataclass
class QAShard:
    category: str
    focus: str
    n_questions: int
    retrieval_query: str


@dataclass
class QAItem:
    category: str
    level: str
    question: str
    ideal_answer: str
    evidence: list[QAEvidence] = field(default_factory=list)
    difficulty: int = 3
    tags: list[str] = field(default_factory=list)
    follow_up_axes: list[str] = field(default_factory=list)
    # Resume-scope context only: { "claim", "claim_section", "source_project_id" }.
    meta: dict | None = None
