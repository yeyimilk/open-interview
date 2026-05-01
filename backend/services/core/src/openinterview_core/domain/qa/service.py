"""QAGenerationService: orchestrates planner -> sharded generators -> merger -> persistence."""
from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...infra.db.qa_repository import SqlQARepository
from ...infra.db.project_repository import SqlProjectRepository
from ...infra.vector import VectorStore, vector_collection_for_user_project
from ..projects.embedder import GatewayEmbedder
from .generator import ShardGenerator
from .merger import QAMerger
from .planner import QAPlanner


class QAGenerationService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        gateway,
        vector_store: VectorStore,
        chat_logical_model: str = "chat-strong",
        embed_logical_model: str = "embed-default",
        max_total_per_set: int = 25,
    ) -> None:
        self._sm = sessionmaker
        self._gw = gateway
        self._vs = vector_store
        self._chat = chat_logical_model
        self._embed = embed_logical_model
        self._max = max_total_per_set

    async def run(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        position: str,
        level: str,
    ) -> UUID:
        # Ensure (or create) qa_set; mark running.
        async with self._sm() as s:
            repo = SqlQARepository(s)
            qa_set = await repo.get_or_create_set(
                user_id=user_id, project_id=project_id, position=position, level=level
            )
            await repo.set_status(qa_set_id=qa_set.id, status="running", error=None)
            qa_set_id = qa_set.id

        try:
            await self._run_inner(
                user_id=user_id,
                project_id=project_id,
                qa_set_id=qa_set_id,
                position=position,
                level=level,
            )
        except Exception as e:
            async with self._sm() as s:
                await SqlQARepository(s).set_status(
                    qa_set_id=qa_set_id, status="failed", error=str(e)[:500]
                )
            raise
        return qa_set_id

    async def _run_inner(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        qa_set_id: UUID,
        position: str,
        level: str,
    ) -> None:
        async with self._sm() as s:
            project = await SqlProjectRepository(s).get(
                user_id=user_id, project_id=project_id
            )
        if project is None:
            raise ValueError("project not found")

        planner = QAPlanner(gateway=self._gw, logical_model=self._chat)
        shards = await planner.plan(
            user_id=user_id,
            project_name=project.name,
            project_summary=project.summary,
            architecture=project.architecture if isinstance(project.architecture, dict) else None,
            position=position,
            level=level,
        )

        embedder = GatewayEmbedder(self._gw, logical_model=self._embed)
        coll = vector_collection_for_user_project(str(user_id), str(project_id))
        gen = ShardGenerator(
            gateway=self._gw,
            embedder=embedder,
            vector_store=self._vs,
            collection=coll,
            logical_model=self._chat,
        )

        # Concurrency-bounded fan-out per shard.
        sem = asyncio.Semaphore(3)

        async def _one(sh):
            async with sem:
                try:
                    return await gen.generate(
                        user_id=user_id,
                        project_name=project.name,
                        project_summary=project.summary,
                        shard=sh,
                        level=level,
                    )
                except Exception:
                    return []

        item_lists = await asyncio.gather(*(_one(s) for s in shards))

        merger = QAMerger(max_total=self._max)
        merged = merger.merge(item_lists)

        async with self._sm() as s:
            repo = SqlQARepository(s)
            await repo.replace_items(
                qa_set_id=qa_set_id, user_id=user_id, items=merged
            )
            await repo.set_status(qa_set_id=qa_set_id, status="ready")
