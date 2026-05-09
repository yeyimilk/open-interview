from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import ClaimMapping, Resume


class SqlResumeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self, *, user_id: UUID, original_filename: str, content_type: str, text: str | None
    ) -> Resume:
        row = Resume(
            user_id=user_id,
            original_filename=original_filename,
            content_type=content_type,
            text=text,
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def get(self, *, user_id: UUID, resume_id: UUID) -> Resume | None:
        q = select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
        return (await self._s.execute(q)).scalar_one_or_none()

    async def list_for_user(self, *, user_id: UUID) -> list[Resume]:
        q = (
            select(Resume)
            .where(Resume.user_id == user_id)
            .order_by(Resume.created_at.desc())
        )
        return list((await self._s.execute(q)).scalars())

    async def delete(self, *, user_id: UUID, resume_id: UUID) -> bool:
        row = await self.get(user_id=user_id, resume_id=resume_id)
        if row is None:
            return False
        await self._s.execute(
            delete(ClaimMapping).where(ClaimMapping.resume_id == resume_id)
        )
        await self._s.delete(row)
        await self._s.commit()
        return True

    async def save_parsed(self, *, resume_id: UUID, parsed: dict) -> None:
        row = await self._s.get(Resume, resume_id)
        if row:
            row.parsed = parsed
            await self._s.commit()

    async def replace_mappings(
        self,
        *,
        user_id: UUID,
        resume_id: UUID,
        mappings: list[tuple],
    ) -> None:
        await self._s.execute(
            delete(ClaimMapping).where(ClaimMapping.resume_id == resume_id)
        )
        for raw in mappings:
            claim, project_id, grounding, confidence = raw[:4]
            section = raw[4] if len(raw) > 4 else None
            category = raw[5] if len(raw) > 5 else None
            self._s.add(
                ClaimMapping(
                    user_id=user_id,
                    resume_id=resume_id,
                    claim=claim,
                    section=section,
                    category=category,
                    project_id=project_id,
                    grounding=grounding,
                    confidence=confidence,
                )
            )
        await self._s.commit()

    async def list_mappings(self, *, user_id: UUID, resume_id: UUID) -> list[ClaimMapping]:
        q = (
            select(ClaimMapping)
            .where(ClaimMapping.user_id == user_id, ClaimMapping.resume_id == resume_id)
            .order_by(ClaimMapping.created_at.asc())
        )
        return list((await self._s.execute(q)).scalars())
