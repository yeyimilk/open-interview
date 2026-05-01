from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CodeChunk:
    rel_path: str
    language: str
    text: str
    symbol: str | None  # function/class name, when known
    start_line: int
    end_line: int


@dataclass(frozen=True)
class DocChunk:
    rel_path: str
    text: str
    section: str | None
    start_line: int
    end_line: int


@dataclass(frozen=True)
class FileSummary:
    rel_path: str
    language: str | None
    bytes: int
    summary: str


@dataclass(frozen=True)
class ModuleSummary:
    folder: str
    summary: str
    file_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectArchitecture:
    summary: str
    components: list[dict] = field(default_factory=list)  # [{name, role, deps}]


@dataclass(frozen=True)
class InterestingDecision:
    title: str
    detail: str
    refs: list[str] = field(default_factory=list)  # rel_paths
