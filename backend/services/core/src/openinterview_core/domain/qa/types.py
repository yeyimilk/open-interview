from __future__ import annotations

from dataclasses import dataclass, field


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
    # Resume-scope context only: { "claim", "claim_section", "source_project_id" }.
    meta: dict | None = None
