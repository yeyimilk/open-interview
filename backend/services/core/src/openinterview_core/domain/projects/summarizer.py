"""Summarizer + diagram + interesting-decisions interfaces.

Concrete LLM implementations call the Gateway. They are split into small
single-responsibility classes per the spec; each method is replayable.
"""
from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

from openinterview_schemas import ChatMessage

from .types import (
    FileSummary,
    InterestingDecision,
    ModuleSummary,
    ProjectArchitecture,
)


class Summarizer(Protocol):
    async def summarize_file(
        self, *, user_id: UUID, rel_path: str, language: str | None, code: str
    ) -> str: ...

    async def summarize_module(
        self, *, user_id: UUID, folder: str, file_summaries: list[FileSummary]
    ) -> str: ...

    async def summarize_project(
        self, *, user_id: UUID, project_name: str, module_summaries: list[ModuleSummary]
    ) -> ProjectArchitecture: ...


class DiagramGenerator(Protocol):
    async def component_diagram(
        self, *, user_id: UUID, architecture: ProjectArchitecture
    ) -> str: ...


class InterestingExtractor(Protocol):
    async def extract(
        self,
        *,
        user_id: UUID,
        architecture: ProjectArchitecture,
        module_summaries: list[ModuleSummary],
    ) -> list[InterestingDecision]: ...


# ---------- LLM-backed implementations ----------

class LLMSummarizer(Summarizer):
    def __init__(self, gateway, logical_model: str = "chat-fast") -> None:
        self._gw = gateway
        self._model = logical_model

    async def summarize_file(self, *, user_id, rel_path, language, code) -> str:  # type: ignore[override]
        prompt = (
            f"Summarize this {language or 'source'} file in 3-5 sentences. "
            f"Include: purpose, key public symbols, notable dependencies. "
            f"Path: {rel_path}\n\n```\n{code[:8000]}\n```"
        )
        return await self._chat(user_id, prompt)

    async def summarize_module(self, *, user_id, folder, file_summaries) -> str:  # type: ignore[override]
        body = "\n".join(
            f"- {fs.rel_path}: {fs.summary}" for fs in file_summaries[:50]
        )
        prompt = (
            f"You are reading a folder named '{folder}'. Below are per-file summaries. "
            f"Write a 4-6 sentence module summary covering responsibilities, key components, "
            f"and how files relate.\n\n{body}"
        )
        return await self._chat(user_id, prompt)

    async def summarize_project(self, *, user_id, project_name, module_summaries) -> ProjectArchitecture:  # type: ignore[override]
        body = "\n".join(
            f"- {ms.folder}: {ms.summary}" for ms in module_summaries[:50]
        )
        prompt = (
            f"Project '{project_name}' module summaries below.\n{body}\n\n"
            "Reply as STRICT JSON with keys: summary (string, 6-10 sentences) and "
            "components (list of {{name, role, deps:[name,...]}}). No prose, only JSON."
        )
        text = await self._chat(user_id, prompt)
        data = _safe_json(text, default={"summary": text, "components": []})
        return ProjectArchitecture(
            summary=str(data.get("summary", "")),
            components=list(data.get("components", []) or []),
        )

    async def _chat(self, user_id: UUID, prompt: str) -> str:
        r = await self._gw.chat(
            user_id=user_id,
            logical_model=self._model,
            messages=[ChatMessage(role="user", content=prompt)],
        )
        return r.content.strip()


class LLMDiagramGenerator(DiagramGenerator):
    def __init__(self, gateway, logical_model: str = "chat-fast") -> None:
        self._gw = gateway
        self._model = logical_model

    async def component_diagram(self, *, user_id, architecture) -> str:  # type: ignore[override]
        body = json.dumps(
            {"summary": architecture.summary, "components": architecture.components}
        )
        prompt = (
            "Produce a Mermaid 'flowchart LR' diagram for this architecture. "
            "Output ONLY the mermaid block contents (no fences, no prose). "
            f"Architecture JSON:\n{body}"
        )
        r = await self._gw.chat(
            user_id=user_id,
            logical_model=self._model,
            messages=[ChatMessage(role="user", content=prompt)],
        )
        return _strip_mermaid_fences(r.content.strip())


class LLMInterestingExtractor(InterestingExtractor):
    def __init__(self, gateway, logical_model: str = "chat-fast") -> None:
        self._gw = gateway
        self._model = logical_model

    async def extract(self, *, user_id, architecture, module_summaries) -> list[InterestingDecision]:  # type: ignore[override]
        body = json.dumps(
            {
                "architecture": architecture.summary,
                "modules": [
                    {"folder": m.folder, "summary": m.summary} for m in module_summaries
                ],
            }
        )
        prompt = (
            "Identify 5-10 'interesting technical decisions' in this project that an interviewer "
            "would dig into (technology choices, tradeoffs, scaling, security, novel patterns). "
            "Reply as STRICT JSON: list of {title, detail, refs:[folder,...]}. JSON only.\n\n" + body
        )
        r = await self._gw.chat(
            user_id=user_id,
            logical_model=self._model,
            messages=[ChatMessage(role="user", content=prompt)],
        )
        data = _safe_json(r.content, default=[])
        out: list[InterestingDecision] = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                out.append(
                    InterestingDecision(
                        title=str(item.get("title", "")).strip()[:200],
                        detail=str(item.get("detail", "")).strip(),
                        refs=[str(x) for x in (item.get("refs") or [])],
                    )
                )
        return out


def _safe_json(text: str, *, default):
    try:
        cleaned = _strip_code_fences(text)
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return default


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


def _strip_mermaid_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```mermaid"):
        s = s[len("```mermaid"):].lstrip()
    elif s.startswith("```"):
        s = s[3:].lstrip()
    if s.endswith("```"):
        s = s[: -3].rstrip()
    return s.strip()
