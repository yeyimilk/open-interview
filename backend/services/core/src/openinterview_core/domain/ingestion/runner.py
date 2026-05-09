"""High-level orchestration: runs the project + resume ingestion pipelines and
persists results. Decoupled from HTTP and from the worker queue.
"""
from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from openinterview_storage import BlobStorage, paths

from ...infra.db.project_repository import (
    SqlIngestRepository,
    SqlProjectRepository,
)
from ...infra.db.resume_repository import SqlResumeRepository
from ...infra.vector import (
    VectorStore,
    vector_collection_for_user_project,
)
from ..projects import (
    CodeChunker,
    DocChunker,
    LLMDiagramGenerator,
    LLMInterestingExtractor,
    LLMSummarizer,
    ProjectIngestPipeline,
    ZipExtractor,
)
from ..projects.embedder import GatewayEmbedder
from ..projects.pipeline import IngestStatusReporter
from ..retrieval import InProcessRetrievalService
from ..resumes import (
    LLMClaimMapper,
    LLMResumeParser,
    ResumeTextExtractor,
)


class DbStatusReporter(IngestStatusReporter):
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], run_id: UUID) -> None:
        self._sm = sessionmaker
        self._run_id = run_id

    async def report(self, *, step: str, progress: int) -> None:  # type: ignore[override]
        async with self._sm() as s:
            await SqlIngestRepository(s).update(
                run_id=self._run_id, step=step, progress=progress, status="running"
            )


class IngestionRunner:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        blob: BlobStorage,
        vector_store: VectorStore,
        gateway,
        chat_logical_model: str = "chat-fast",
        embed_logical_model: str = "embed-default",
    ) -> None:
        self._sm = sessionmaker
        self._blob = blob
        self._vec = vector_store
        self._gw = gateway
        self._chat_model = chat_logical_model
        self._embed_model = embed_logical_model
        self._retrieval = InProcessRetrievalService(
            sessionmaker=sessionmaker,
            gateway=gateway,
            vector_store=vector_store,
            embed_logical_model=embed_logical_model,
        )

    # ------------ project ------------

    async def run_project(self, *, user_id: UUID, project_id: UUID, run_id: UUID) -> None:
        async with self._sm() as s:
            project = await SqlProjectRepository(s).get(user_id=user_id, project_id=project_id)
        if project is None:
            raise ValueError("project not found")

        # Load uploaded zip from blob storage.
        # Convention: stored at users/<uid>/projects/<pid>/source.zip during upload.
        try:
            zip_bytes = await self._blob.get_bytes(_project_zip_path(user_id, project_id))
        except Exception as e:
            await self._fail(run_id, f"missing source zip: {e}")
            return

        pipeline = self._build_project_pipeline(user_id=user_id, project_id=project_id)
        reporter = DbStatusReporter(self._sm, run_id)

        try:
            output = await pipeline.run(
                user_id=user_id,
                project_id=project_id,
                project_name=project.name,
                zip_bytes=zip_bytes,
                reporter=reporter,
            )
        except Exception as e:
            await self._fail(run_id, str(e))
            return

        # Persist results.
        async with self._sm() as s:
            repo = SqlProjectRepository(s)
            await repo.replace_files(
                user_id=user_id,
                project_id=project_id,
                files=[
                    (f.rel_path, f.language, f.bytes, f.summary) for f in output.files
                ],
            )
            await repo.save_summaries(
                user_id=user_id,
                project_id=project_id,
                project_summary=(output.architecture.summary if output.architecture else None),
                architecture=(asdict(output.architecture) if output.architecture else None),
                interesting_decisions=[asdict(d) for d in output.interesting] or None,
            )
            diagrams = []
            if output.component_diagram_mermaid:
                diagrams.append(("component", "component", output.component_diagram_mermaid))
            await repo.replace_diagrams(user_id=user_id, project_id=project_id, diagrams=diagrams)
            await repo.update_status(project_id=project_id, status="ready")

        async with self._sm() as s:
            await SqlIngestRepository(s).update(
                run_id=run_id, status="done", step="done", progress=100
            )

        # Fire-and-forget: auto-generate default QA sets so the user has
        # something to play with without clicking anything.
        try:
            from ..qa import QAGenerationService

            svc = QAGenerationService(
                sessionmaker=self._sm,
                gateway=self._gw,
                vector_store=self._vec,
                retrieval_service=self._retrieval,
                chat_logical_model=self._chat_model,
                embed_logical_model=self._embed_model,
            )
            import asyncio as _asyncio

            for lvl in ("junior", "mid", "senior", "tech_lead"):
                _asyncio.create_task(
                    svc.run(
                        user_id=user_id,
                        project_id=project_id,
                        position="swe_generic",
                        level=lvl,
                    )
                )
        except Exception:
            pass

    def _build_project_pipeline(self, *, user_id: UUID, project_id: UUID) -> ProjectIngestPipeline:
        embedder = GatewayEmbedder(self._gw, logical_model=self._embed_model)
        summarizer = LLMSummarizer(self._gw, logical_model=self._chat_model)
        diagrams = LLMDiagramGenerator(self._gw, logical_model=self._chat_model)
        interesting = LLMInterestingExtractor(self._gw, logical_model=self._chat_model)

        async def _upsert(collection, records, embeddings):
            await self._vec.upsert(collection=collection, records=records, embeddings=embeddings)

        return ProjectIngestPipeline(
            extractor=ZipExtractor(),
            code_chunker=CodeChunker(),
            doc_chunker=DocChunker(),
            embedder=embedder,
            summarizer=summarizer,
            diagrams=diagrams,
            interesting=interesting,
            vector_upsert=_upsert,
            vector_collection=vector_collection_for_user_project(str(user_id), str(project_id)),
        )

    # ------------ resume ------------

    async def run_resume(
        self,
        *,
        user_id: UUID,
        resume_id: UUID,
        run_id: UUID,
        project_ids: list[UUID],
    ) -> None:
        async with self._sm() as s:
            resume = await SqlResumeRepository(s).get(user_id=user_id, resume_id=resume_id)
        if resume is None or not resume.text:
            await self._fail(run_id, "resume missing or has no text")
            return

        reporter = DbStatusReporter(self._sm, run_id)
        await reporter.report(step="parse", progress=20)

        parser = LLMResumeParser(self._gw, logical_model=self._chat_model)
        try:
            parsed = await parser.parse(user_id=user_id, text=resume.text)
        except Exception as e:
            await self._fail(run_id, f"parse failed: {e}")
            return

        async with self._sm() as s:
            await SqlResumeRepository(s).save_parsed(
                resume_id=resume_id,
                parsed={
                    "name": parsed.name,
                    "contacts": parsed.contacts,
                    "skills": parsed.skills,
                    "experience": parsed.experience,
                    "projects": parsed.projects,
                    "education": parsed.education,
                    "claims": [
                        {"text": c.text, "section": c.section, "category": c.category}
                        for c in parsed.claims
                    ],
                },
            )

        await reporter.report(step="ground_claims", progress=60)

        mapper = LLMClaimMapper(
            gateway=self._gw,
            retrieval_service=self._retrieval,
            logical_model=self._chat_model,
        )
        try:
            mappings = await mapper.map(
                user_id=user_id, claims=parsed.claims, project_ids=project_ids
            )
        except Exception as e:
            await self._fail(run_id, f"claim mapping failed: {e}")
            return

        async with self._sm() as s:
            await SqlResumeRepository(s).replace_mappings(
                user_id=user_id,
                resume_id=resume_id,
                mappings=[
                    (
                        m.claim,
                        UUID(m.project_id) if m.project_id else None,
                        m.grounding or None,
                        m.confidence,
                        m.section,
                        m.category,
                    )
                    for m in mappings
                ],
            )

        async with self._sm() as s:
            await SqlIngestRepository(s).update(
                run_id=run_id, status="done", step="done", progress=100
            )

    # ------------ helpers ------------

    async def _fail(self, run_id: UUID, error: str) -> None:
        async with self._sm() as s:
            await SqlIngestRepository(s).update(run_id=run_id, status="failed", error=error)


def _project_zip_path(user_id: UUID, project_id: UUID) -> str:
    return f"{paths.user_root(user_id)}/projects/{project_id}/source.zip"
