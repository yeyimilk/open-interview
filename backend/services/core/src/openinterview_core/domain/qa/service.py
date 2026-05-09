"""Compatibility facade for question-set generation.

New orchestration lives in ``domain.question_sets``. This class keeps the
existing API, messenger, and ingestion call sites stable.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...infra.vector import VectorStore
from ..question_sets import QuestionSetGenerationRequest, QuestionSetService
from ..retrieval import RetrievalService


class QAGenerationService:
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
    ) -> None:
        self._question_sets = QuestionSetService(
            sessionmaker=sessionmaker,
            gateway=gateway,
            vector_store=vector_store,
            retrieval_service=retrieval_service,
            chat_logical_model=chat_logical_model,
            embed_logical_model=embed_logical_model,
            max_total_per_set=max_total_per_set,
        )

    async def run(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        position: str,
        level: str,
    ) -> UUID:
        result = await self._question_sets.generate(
            QuestionSetGenerationRequest(
                user_id=user_id,
                project_id=project_id,
                position=position,
                level=level,
                scope="project",
            )
        )
        return result.qa_set_id

    async def run_for_resume(
        self,
        *,
        user_id: UUID,
        resume_id: UUID,
        position: str,
        level: str,
    ) -> UUID:
        result = await self._question_sets.generate(
            QuestionSetGenerationRequest(
                user_id=user_id,
                resume_id=resume_id,
                position=position,
                level=level,
                scope="resume",
            )
        )
        return result.qa_set_id
