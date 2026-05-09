from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import QAItem as QAItemModel
from openinterview_db import QAGenerationRun, QAGenerationShard, QASet

_UNSET = object()


class SqlQARepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_or_create_set(
        self, *, user_id: UUID, project_id: UUID, position: str, level: str
    ) -> QASet:
        """Project-scoped QA set (legacy / single-project flow)."""
        q = select(QASet).where(
            QASet.user_id == user_id,
            QASet.scope == "project",
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
            resume_id=None,
            scope="project",
            position=position,
            level=level,
            status="pending",
            total=0,
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def get_or_create_set_for_resume(
        self, *, user_id: UUID, resume_id: UUID, position: str, level: str
    ) -> QASet:
        """Resume-scoped QA set (preferred)."""
        q = select(QASet).where(
            QASet.user_id == user_id,
            QASet.scope == "resume",
            QASet.resume_id == resume_id,
            QASet.position == position,
            QASet.level == level,
        )
        existing = (await self._s.execute(q)).scalar_one_or_none()
        if existing:
            return existing
        row = QASet(
            user_id=user_id,
            project_id=None,
            resume_id=resume_id,
            scope="resume",
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

    async def get_set_any(self, *, qa_set_id: UUID) -> QASet | None:
        return await self._s.get(QASet, qa_set_id)

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
        self, *, qa_set_id: UUID, status: str, error: str | None | object = _UNSET
    ) -> None:
        row = await self._s.get(QASet, qa_set_id)
        if not row:
            return
        row.status = status
        if error is not _UNSET:
            row.error = error
        await self._s.commit()

    async def set_review(
        self,
        *,
        qa_set_id: UUID,
        reviewer_user_id: UUID,
        review_status: str,
        review_notes: str | None = None,
    ) -> QASet | None:
        row = await self._s.get(QASet, qa_set_id)
        if row is None:
            return None
        row.review_status = review_status
        row.review_notes = review_notes.strip()[:2000] if review_notes else None
        row.reviewer_user_id = reviewer_user_id
        row.reviewed_at = datetime.now(timezone.utc)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def list_sets(
        self,
        *,
        user_id: UUID | None = None,
        status: str | None = None,
        review_status: str | None = None,
        limit: int = 100,
    ) -> list[QASet]:
        q = select(QASet).order_by(QASet.created_at.desc()).limit(max(1, min(limit, 500)))
        if user_id is not None:
            q = q.where(QASet.user_id == user_id)
        if status:
            q = q.where(QASet.status == status)
        if review_status:
            q = q.where(QASet.review_status == review_status)
        return list((await self._s.execute(q)).scalars())

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
                    follow_up_axes=getattr(it, "follow_up_axes", None) or [],
                    meta=getattr(it, "meta", None),
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

    async def create_generation_run(
        self,
        *,
        qa_set_id: UUID,
        user_id: UUID,
        scope: str,
        trigger: str = "manual",
        meta: dict | None = None,
    ) -> QAGenerationRun:
        latest = await self.latest_generation_run(qa_set_id=qa_set_id)
        row = QAGenerationRun(
            qa_set_id=qa_set_id,
            user_id=user_id,
            scope=scope,
            status="running",
            attempt=(latest.attempt + 1) if latest else 1,
            trigger=trigger,
            meta=meta or {},
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def latest_generation_run(self, *, qa_set_id: UUID) -> QAGenerationRun | None:
        q = (
            select(QAGenerationRun)
            .where(QAGenerationRun.qa_set_id == qa_set_id)
            .order_by(QAGenerationRun.created_at.desc())
        )
        return (await self._s.execute(q)).scalars().first()

    async def finish_generation_run(
        self,
        *,
        run_id: UUID,
        status: str,
        error: str | None = None,
        meta: dict | None = None,
    ) -> None:
        row = await self._s.get(QAGenerationRun, run_id)
        if row is None:
            return
        row.status = status
        row.error = error[:1000] if error else None
        if meta is not None:
            row.meta = meta
        row.completed_at = datetime.now(timezone.utc)
        await self._s.commit()

    async def upsert_generation_shard(
        self,
        *,
        run_id: UUID,
        qa_set_id: UUID,
        shard_key: str,
        category: str | None,
        status: str,
        item_count: int = 0,
        error: str | None = None,
        meta: dict | None = None,
    ) -> QAGenerationShard:
        row = QAGenerationShard(
            run_id=run_id,
            qa_set_id=qa_set_id,
            shard_key=shard_key[:240],
            category=category,
            status=status,
            item_count=max(0, int(item_count or 0)),
            error=error[:1000] if error else None,
            meta=meta or {},
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def list_generation_shards(self, *, run_id: UUID) -> list[QAGenerationShard]:
        q = (
            select(QAGenerationShard)
            .where(QAGenerationShard.run_id == run_id)
            .order_by(QAGenerationShard.created_at.asc())
        )
        return list((await self._s.execute(q)).scalars())
