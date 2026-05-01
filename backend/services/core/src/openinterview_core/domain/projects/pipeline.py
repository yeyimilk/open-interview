"""Project ingestion pipeline.

Pure orchestration: takes interfaces (storage, vector, embedder, summarizer,
diagram, interesting) and produces structured outputs that the worker
persists. No HTTP, no SQL.

Each step is small and independently testable.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from .chunker import CodeChunker, DocChunker
from .embedder import Embedder
from .extractor import ZipExtractor
from .languages import detect_language
from .summarizer import (
    DiagramGenerator,
    InterestingExtractor,
    Summarizer,
)
from .types import (
    CodeChunk,
    DocChunk,
    FileSummary,
    InterestingDecision,
    ModuleSummary,
    ProjectArchitecture,
)


class IngestStatusReporter(Protocol):
    async def report(self, *, step: str, progress: int) -> None: ...


class _NoopReporter(IngestStatusReporter):
    async def report(self, *, step: str, progress: int) -> None:  # type: ignore[override]
        return None


@dataclass
class IngestOutput:
    files: list[FileSummary] = field(default_factory=list)
    modules: list[ModuleSummary] = field(default_factory=list)
    architecture: ProjectArchitecture | None = None
    component_diagram_mermaid: str | None = None
    interesting: list[InterestingDecision] = field(default_factory=list)


@dataclass
class _RawFile:
    rel_path: str
    text: str
    language: str | None
    size: int


class ProjectIngestPipeline:
    def __init__(
        self,
        *,
        extractor: ZipExtractor,
        code_chunker: CodeChunker,
        doc_chunker: DocChunker,
        embedder: Embedder,
        summarizer: Summarizer,
        diagrams: DiagramGenerator,
        interesting: InterestingExtractor,
        vector_upsert: Callable,  # async (collection, records, embeddings) -> None
        vector_collection: str,
    ) -> None:
        self._extractor = extractor
        self._code = code_chunker
        self._doc = doc_chunker
        self._embed = embedder
        self._summarizer = summarizer
        self._diagrams = diagrams
        self._interesting = interesting
        self._upsert = vector_upsert
        self._collection = vector_collection

    async def run(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        project_name: str,
        zip_bytes: bytes,
        reporter: IngestStatusReporter | None = None,
    ) -> IngestOutput:
        rep = reporter or _NoopReporter()

        await rep.report(step="extract", progress=2)
        raw = self._collect_raw(zip_bytes)

        await rep.report(step="chunk", progress=10)
        code_chunks, doc_chunks = self._chunk_all(raw)

        await rep.report(step="embed", progress=25)
        await self._embed_and_upsert(
            user_id=user_id, project_id=project_id, code=code_chunks, docs=doc_chunks
        )

        await rep.report(step="summarize_files", progress=45)
        file_summaries = await self._summarize_files(user_id, raw)

        await rep.report(step="summarize_modules", progress=70)
        modules = await self._summarize_modules(user_id, file_summaries)

        await rep.report(step="architecture", progress=82)
        arch = await self._summarizer.summarize_project(
            user_id=user_id, project_name=project_name, module_summaries=modules
        )

        await rep.report(step="diagram", progress=90)
        diagram = ""
        try:
            diagram = await self._diagrams.component_diagram(
                user_id=user_id, architecture=arch
            )
        except Exception:
            diagram = ""

        await rep.report(step="interesting", progress=96)
        interesting: list[InterestingDecision] = []
        try:
            interesting = await self._interesting.extract(
                user_id=user_id, architecture=arch, module_summaries=modules
            )
        except Exception:
            interesting = []

        await rep.report(step="done", progress=100)
        return IngestOutput(
            files=file_summaries,
            modules=modules,
            architecture=arch,
            component_diagram_mermaid=diagram or None,
            interesting=interesting,
        )

    # -------------------- steps --------------------

    def _collect_raw(self, zip_bytes: bytes) -> list[_RawFile]:
        out: list[_RawFile] = []
        for entry in self._extractor.extract(zip_bytes):
            try:
                text = entry.data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if not text.strip():
                continue
            lang = detect_language(entry.rel_path)
            out.append(
                _RawFile(rel_path=entry.rel_path, text=text, language=lang, size=len(entry.data))
            )
        return out

    def _chunk_all(self, raw: list[_RawFile]) -> tuple[list[CodeChunk], list[DocChunk]]:
        code: list[CodeChunk] = []
        docs: list[DocChunk] = []
        for r in raw:
            if r.language == "doc" or r.language is None and r.rel_path.lower().endswith(
                (".md", ".rst", ".txt")
            ):
                docs.extend(self._doc.chunk(rel_path=r.rel_path, text=r.text))
            elif r.language and r.language != "doc":
                code.extend(
                    self._code.chunk(rel_path=r.rel_path, language=r.language, text=r.text)
                )
        return code, docs

    async def _embed_and_upsert(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        code: list[CodeChunk],
        docs: list[DocChunk],
    ) -> None:
        records, texts = _records_for_chunks(project_id, code, docs)
        if not records:
            return
        # Batch embeddings to keep calls reasonable.
        batch = 64
        for i in range(0, len(texts), batch):
            sl = slice(i, i + batch)
            vectors = await self._embed.embed(user_id=user_id, texts=texts[sl])
            await self._upsert(self._collection, records[sl], vectors)

    async def _summarize_files(
        self, user_id: UUID, raw: list[_RawFile]
    ) -> list[FileSummary]:
        # Concurrency-bounded fan-out
        sem = asyncio.Semaphore(8)

        async def _one(r: _RawFile) -> FileSummary:
            async with sem:
                summary = await self._summarizer.summarize_file(
                    user_id=user_id,
                    rel_path=r.rel_path,
                    language=r.language,
                    code=r.text,
                )
            return FileSummary(rel_path=r.rel_path, language=r.language, bytes=r.size, summary=summary)

        return list(await asyncio.gather(*(_one(r) for r in raw)))

    async def _summarize_modules(
        self, user_id: UUID, file_summaries: list[FileSummary]
    ) -> list[ModuleSummary]:
        groups: dict[str, list[FileSummary]] = {}
        for fs in file_summaries:
            folder = os.path.dirname(fs.rel_path) or "."
            groups.setdefault(folder, []).append(fs)

        out: list[ModuleSummary] = []
        sem = asyncio.Semaphore(4)

        async def _one(folder: str, files: list[FileSummary]) -> ModuleSummary:
            async with sem:
                summary = await self._summarizer.summarize_module(
                    user_id=user_id, folder=folder, file_summaries=files
                )
            return ModuleSummary(
                folder=folder,
                summary=summary,
                file_paths=[f.rel_path for f in files],
            )

        results = await asyncio.gather(*(_one(folder, files) for folder, files in groups.items()))
        out.extend(results)
        return out


def _records_for_chunks(
    project_id: UUID, code: list[CodeChunk], docs: list[DocChunk]
) -> tuple[list, list[str]]:
    from ...infra.vector import VectorRecord

    records: list[VectorRecord] = []
    texts: list[str] = []
    for c in code:
        rid = f"code:{project_id}:{c.rel_path}:{c.start_line}-{c.end_line}:{c.symbol or ''}"
        rid = _stable_id(rid)
        records.append(
            VectorRecord(
                id=rid,
                text=c.text,
                metadata={
                    "kind": "code",
                    "rel_path": c.rel_path,
                    "language": c.language,
                    "symbol": c.symbol or "",
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "project_id": str(project_id),
                },
            )
        )
        texts.append(c.text)
    for d in docs:
        rid = _stable_id(f"doc:{project_id}:{d.rel_path}:{d.start_line}-{d.end_line}")
        records.append(
            VectorRecord(
                id=rid,
                text=d.text,
                metadata={
                    "kind": "doc",
                    "rel_path": d.rel_path,
                    "section": d.section or "",
                    "start_line": d.start_line,
                    "end_line": d.end_line,
                    "project_id": str(project_id),
                },
            )
        )
        texts.append(d.text)
    return records, texts


def _stable_id(s: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, s))
