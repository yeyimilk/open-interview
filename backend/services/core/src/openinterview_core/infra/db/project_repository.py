from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import (
    IngestRun,
    Project,
    ProjectDiagram,
    ProjectFile,
)


class SqlProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, *, user_id: UUID, name: str, source_type: str, source_uri: str | None = None) -> Project:
        row = Project(user_id=user_id, name=name, source_type=source_type, source_uri=source_uri)
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def get(self, *, user_id: UUID, project_id: UUID) -> Project | None:
        q = select(Project).where(Project.id == project_id, Project.user_id == user_id)
        return (await self._s.execute(q)).scalar_one_or_none()

    async def list(self, *, user_id: UUID) -> list[Project]:
        q = select(Project).where(Project.user_id == user_id).order_by(Project.created_at.desc())
        return list((await self._s.execute(q)).scalars())

    async def update_status(self, *, project_id: UUID, status: str) -> None:
        p = await self._s.get(Project, project_id)
        if p:
            p.status = status
            await self._s.commit()

    async def save_summaries(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        project_summary: str | None,
        architecture: dict | None,
        interesting_decisions: list[dict] | None,
    ) -> None:
        p = await self._s.get(Project, project_id)
        if not p:
            return
        p.summary = project_summary
        p.architecture = architecture
        p.interesting_decisions = interesting_decisions
        await self._s.commit()

    async def replace_files(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        files: list[tuple[str, str | None, int, str]],  # (rel_path, lang, bytes, summary)
    ) -> None:
        await self._s.execute(
            delete(ProjectFile).where(ProjectFile.project_id == project_id)
        )
        for rel_path, lang, n, summary in files:
            self._s.add(
                ProjectFile(
                    user_id=user_id,
                    project_id=project_id,
                    rel_path=rel_path,
                    language=lang,
                    bytes=n,
                    summary=summary,
                )
            )
        await self._s.commit()

    async def list_files(self, *, user_id: UUID, project_id: UUID) -> list[ProjectFile]:
        q = (
            select(ProjectFile)
            .where(ProjectFile.user_id == user_id, ProjectFile.project_id == project_id)
            .order_by(ProjectFile.rel_path.asc())
        )
        return list((await self._s.execute(q)).scalars())

    async def replace_diagrams(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        diagrams: list[tuple[str, str, str]],  # (name, kind, mermaid)
    ) -> None:
        await self._s.execute(
            delete(ProjectDiagram).where(ProjectDiagram.project_id == project_id)
        )
        for name, kind, mermaid in diagrams:
            self._s.add(
                ProjectDiagram(
                    user_id=user_id, project_id=project_id, name=name, kind=kind, mermaid=mermaid
                )
            )
        await self._s.commit()

    async def list_diagrams(self, *, user_id: UUID, project_id: UUID) -> list[ProjectDiagram]:
        q = (
            select(ProjectDiagram)
            .where(ProjectDiagram.user_id == user_id, ProjectDiagram.project_id == project_id)
            .order_by(ProjectDiagram.created_at.asc())
        )
        return list((await self._s.execute(q)).scalars())


class SqlIngestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, *, user_id: UUID, kind: str, project_id: UUID | None = None, resume_id: UUID | None = None) -> IngestRun:
        row = IngestRun(
            user_id=user_id, kind=kind, project_id=project_id, resume_id=resume_id, status="pending"
        )
        self._s.add(row)
        await self._s.commit()
        return row

    async def update(self, *, run_id: UUID, status: str | None = None, step: str | None = None, progress: int | None = None, error: str | None = None) -> None:
        row = await self._s.get(IngestRun, run_id)
        if not row:
            return
        if status is not None:
            row.status = status
        if step is not None:
            row.step = step
        if progress is not None:
            row.progress = progress
        if error is not None:
            row.error = error
        await self._s.commit()

    async def get(self, *, user_id: UUID, run_id: UUID) -> IngestRun | None:
        q = select(IngestRun).where(IngestRun.id == run_id, IngestRun.user_id == user_id)
        return (await self._s.execute(q)).scalar_one_or_none()
