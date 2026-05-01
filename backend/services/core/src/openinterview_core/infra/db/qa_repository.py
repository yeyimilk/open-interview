from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import QAItem as QAItemModel
from openinterview_db import QASet


class SqlQARepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_or_create_set(
        self, *, user_id: UUID, project_id: UUID, position: str, level: str
    ) -> QASet:
        q = select(QASet).where(
            QASet.user_id == user_id,
            QASet.project_id == project_id,
            QASet.position == position,
            QASet.level == level,
        )
        existing = (await self._s.execute(q)).scalar_one_or_none()
        if existing:
            return existing
        row = QASet(
            user_id=user_id,
            project_id=project_id,
            position=position,
            level=level,
            status="pending",
            total=0,
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def get_set(self, *, user_id: UUID, qa_set_id: UUID) -> QASet | None:
        q = select(QASet).where(QASet.id == qa_set_id, QASet.user_id == user_id)
        return (await self._s.execute(q)).scalar_one_or_none()

    async def list_sets_for_project(
        self, *, user_id: UUID, project_id: UUID
    ) -> list[QASet]:
        q = (
            select(QASet)
            .where(QASet.user_id == user_id, QASet.project_id == project_id)
            .order_by(QASet.created_at.desc())
        )
        return list((await self._s.execute(q)).scalars())

    async def set_status(
        self, *, qa_set_id: UUID, status: str, error: str | None = None
    ) -> None:
        row = await self._s.get(QASet, qa_set_id)
        if not row:
            return
        row.status = status
        if error is not None:
            row.error = error
        await self._s.commit()

    async def replace_items(
        self, *, qa_set_id: UUID, user_id: UUID, items
    ) -> None:
        await self._s.execute(
            delete(QAItemModel).where(QAItemModel.qa_set_id == qa_set_id)
        )
        n = 0
        for it in items:
            self._s.add(
                QAItemModel(
                    qa_set_id=qa_set_id,
                    user_id=user_id,
                    category=it.category,
                    level=it.level,
                    question=it.question,
                    ideal_answer=it.ideal_answer,
                    evidence=[
                        {
                            "rel_path": e.rel_path,
                            "start_line": e.start_line,
                            "end_line": e.end_line,
                            "snippet": e.snippet,
                        }
                        for e in it.evidence
                    ],
                    difficulty=it.difficulty,
                    tags=it.tags,
                )
            )
            n += 1
        # Update total on the set.
        s = await self._s.get(QASet, qa_set_id)
        if s:
            s.total = n
        await self._s.commit()

    async def list_items(
        self, *, user_id: UUID, qa_set_id: UUID
    ) -> list[QAItemModel]:
        q = (
            select(QAItemModel)
            .where(
                QAItemModel.qa_set_id == qa_set_id,
                QAItemModel.user_id == user_id,
            )
            .order_by(QAItemModel.category, QAItemModel.difficulty.desc())
        )
        return list((await self._s.execute(q)).scalars())

    async def list_items_by_categories(
        self, *, user_id: UUID, qa_set_id: UUID, categories: list[str] | None = None
    ) -> list[QAItemModel]:
        q = select(QAItemModel).where(
            QAItemModel.user_id == user_id, QAItemModel.qa_set_id == qa_set_id
        )
        if categories:
            q = q.where(QAItemModel.category.in_(categories))
        return list((await self._s.execute(q)).scalars())
