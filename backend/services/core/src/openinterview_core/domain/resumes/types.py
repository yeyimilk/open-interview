from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Claim:
    text: str
    section: str | None = None  # experience | projects | skills | education
    category: str | None = None  # impact | leadership | technical_depth | collaboration | delivery


@dataclass(frozen=True)
class ParsedResume:
    raw_text: str
    name: str | None = None
    contacts: dict[str, str] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    experience: list[dict] = field(default_factory=list)  # [{title, company, period, bullets:[...]}]
    projects: list[dict] = field(default_factory=list)
    education: list[dict] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)


@dataclass(frozen=True)
class ResumeClaimMapping:
    claim: str
    project_id: str | None = None
    grounding: list[dict] = field(default_factory=list)  # [{rel_path, start_line, end_line, evidence}]
    confidence: int = 0  # 0..100
    section: str | None = None
    category: str | None = None
