"""Question-set generation boundary.

This owns the lifecycle around planning, sharded generation, merge, and
persistence while lower-level QA modules keep the prompt/retrieval details.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...infra.db.project_repository import SqlProjectRepository
from ...infra.db.qa_repository import SqlQARepository
from ...infra.db.resume_repository import SqlResumeRepository
from ...infra.vector import VectorStore
from ..retrieval import InProcessRetrievalService, RetrievalService

QuestionSetScope = Literal["project", "resume"]


@dataclass(frozen=True)
class QuestionSetGenerationRequest:
    user_id: UUID
    position: str
    level: str
    scope: QuestionSetScope
    project_id: UUID | None = None
    resume_id: UUID | None = None


@dataclass(frozen=True)
class QuestionSetGenerationResult:
    qa_set_id: UUID
    scope: QuestionSetScope
    status: str
    total: int = 0


class QuestionSetService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        gateway,
        vector_store: VectorStore,
        retrieval_service: RetrievalService | None = None,
        chat_logical_model: str = "chat-strong",
        embed_logical_model: str = "embed-default",
        max_total_per_set: int = 25,
        shard_concurrency: int = 3,
    ) -> None:
        self._sm = sessionmaker
        self._gw = gateway
        self._vs = vector_store
        self._retrieval = retrieval_service or InProcessRetrievalService(
            sessionmaker=sessionmaker,
            gateway=gateway,
            vector_store=vector_store,
            embed_logical_model=embed_logical_model,
        )
        self._chat = chat_logical_model
        self._embed = embed_logical_model
        self._max = max_total_per_set
        self._shard_concurrency = max(1, int(shard_concurrency or 1))

    async def generate(
        self, request: QuestionSetGenerationRequest
    ) -> QuestionSetGenerationResult:
        qa_set_id = await self._prepare_set(request)
        async with self._sm() as s:
            run = await SqlQARepository(s).create_generation_run(
                qa_set_id=qa_set_id,
                user_id=request.user_id,
                scope=request.scope,
                trigger="generation",
                meta={
                    "position": request.position,
                    "level": request.level,
                    "project_id": str(request.project_id) if request.project_id else None,
                    "resume_id": str(request.resume_id) if request.resume_id else None,
                },
            )
        try:
            if request.scope == "project":
                merged = await self._generate_project(request, qa_set_id=qa_set_id, run_id=run.id)
            elif request.scope == "resume":
                merged = await self._generate_resume(request, qa_set_id=qa_set_id, run_id=run.id)
            else:
                raise ValueError(f"unsupported question-set scope: {request.scope}")

            async with self._sm() as s:
                repo = SqlQARepository(s)
                await repo.replace_items(
                    qa_set_id=qa_set_id, user_id=request.user_id, items=merged
                )
                await repo.set_status(
                    qa_set_id=qa_set_id, status="ready", error=None
                )
                await repo.finish_generation_run(
                    run_id=run.id,
                    status="ready",
                    meta={"item_count": len(merged)},
                )
            return QuestionSetGenerationResult(
                qa_set_id=qa_set_id,
                scope=request.scope,
                status="ready",
                total=len(merged),
            )
        except Exception as e:
            async with self._sm() as s:
                repo = SqlQARepository(s)
                await repo.set_status(
                    qa_set_id=qa_set_id, status="failed", error=str(e)[:500]
                )
                await repo.finish_generation_run(
                    run_id=run.id, status="failed", error=str(e)[:1000]
                )
            raise

    async def _prepare_set(self, request: QuestionSetGenerationRequest) -> UUID:
        async with self._sm() as s:
            repo = SqlQARepository(s)
            if request.scope == "project":
                if request.project_id is None:
                    raise ValueError("project_id is required for project question sets")
                qa_set = await repo.get_or_create_set(
                    user_id=request.user_id,
                    project_id=request.project_id,
                    position=request.position,
                    level=request.level,
                )
            elif request.scope == "resume":
                if request.resume_id is None:
                    raise ValueError("resume_id is required for resume question sets")
                qa_set = await repo.get_or_create_set_for_resume(
                    user_id=request.user_id,
                    resume_id=request.resume_id,
                    position=request.position,
                    level=request.level,
                )
            else:
                raise ValueError(f"unsupported question-set scope: {request.scope}")
            await repo.set_status(qa_set_id=qa_set.id, status="running", error=None)
            return qa_set.id

    async def _generate_project(
        self, request: QuestionSetGenerationRequest, *, qa_set_id: UUID, run_id: UUID
    ) -> list:
        if request.project_id is None:
            raise ValueError("project_id is required for project question sets")

        from ..qa.generator import ShardGenerator
        from ..qa.merger import QAMerger
        from ..qa.planner import QAPlanner

        async with self._sm() as s:
            project = await SqlProjectRepository(s).get(
                user_id=request.user_id, project_id=request.project_id
            )
        if project is None:
            raise ValueError("project not found")

        planner = QAPlanner(gateway=self._gw, logical_model=self._chat)
        shards = await planner.plan(
            user_id=request.user_id,
            project_name=project.name,
            project_summary=project.summary,
            architecture=(
                project.architecture if isinstance(project.architecture, dict) else None
            ),
            position=request.position,
            level=request.level,
        )

        gen = ShardGenerator(
            gateway=self._gw,
            retrieval_service=self._retrieval,
            project_id=request.project_id,
            logical_model=self._chat,
        )
        item_lists = await self._run_shards(
            [
                (sh.retrieval_query, sh.category, lambda sh=sh: gen.generate(
                    user_id=request.user_id,
                    project_name=project.name,
                    project_summary=project.summary,
                    shard=sh,
                    level=request.level,
                ))
                for sh in shards
            ],
            qa_set_id=qa_set_id,
            run_id=run_id,
        )
        return QAMerger(max_total=self._max).merge(item_lists)

    async def _generate_resume(
        self, request: QuestionSetGenerationRequest, *, qa_set_id: UUID, run_id: UUID
    ) -> list:
        if request.resume_id is None:
            raise ValueError("resume_id is required for resume question sets")

        from ..qa.merger import QAMerger
        from ..qa.resume_generator import ResumeShardGenerator
        from ..qa.resume_planner import plan_for_resume

        async with self._sm() as s:
            resume = await SqlResumeRepository(s).get(
                user_id=request.user_id, resume_id=request.resume_id
            )
            mappings = await SqlResumeRepository(s).list_mappings(
                user_id=request.user_id, resume_id=request.resume_id
            )
        if resume is None:
            raise ValueError("resume not found")

        parsed = resume.parsed if isinstance(resume.parsed, dict) else {}
        candidate_name = parsed.get("name") if isinstance(parsed, dict) else None
        shards, ctx_by_query = plan_for_resume(
            parsed=parsed,
            claim_mappings=list(mappings),
            position=request.position,
            level=request.level,
        )

        gen = ResumeShardGenerator(
            gateway=self._gw,
            retrieval_service=self._retrieval,
            logical_model=self._chat,
        )
        item_lists = await self._run_shards(
            [
                (sh.retrieval_query, sh.category, lambda sh=sh, ctx=ctx_by_query.get(sh.retrieval_query): (
                    gen.generate(
                        user_id=request.user_id,
                        shard=sh,
                        context=ctx,
                        level=request.level,
                        candidate_name=candidate_name,
                    )
                    if ctx is not None
                    else _empty_items()
                ))
                for sh in shards
            ],
            qa_set_id=qa_set_id,
            run_id=run_id,
        )
        return QAMerger(max_total=self._max).merge(item_lists)

    async def _run_shards(self, calls, *, qa_set_id: UUID, run_id: UUID) -> list[list]:
        sem = asyncio.Semaphore(self._shard_concurrency)
        failures = 0

        async def _one(item):
            nonlocal failures
            shard_key, category, call = item
            async with sem:
                try:
                    rows = await call()
                    async with self._sm() as s:
                        await SqlQARepository(s).upsert_generation_shard(
                            run_id=run_id,
                            qa_set_id=qa_set_id,
                            shard_key=shard_key,
                            category=category,
                            status="ready",
                            item_count=len(rows),
                        )
                    return rows
                except Exception as e:
                    failures += 1
                    async with self._sm() as s:
                        await SqlQARepository(s).upsert_generation_shard(
                            run_id=run_id,
                            qa_set_id=qa_set_id,
                            shard_key=shard_key,
                            category=category,
                            status="failed",
                            error=str(e),
                        )
                    return []

        item_lists = await asyncio.gather(*(_one(call) for call in calls))
        if calls and failures == len(calls):
            raise RuntimeError("all question generation shards failed")
        return item_lists


async def _empty_items() -> list:
    return []
