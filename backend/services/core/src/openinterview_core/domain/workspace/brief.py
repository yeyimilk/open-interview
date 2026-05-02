"""One-line workspace summary for system prompts.

Counts the user's projects and resumes and lists their three most-recent
ready projects. Used by both the WhatsApp /chat path and the in-app
/general session so the LLM knows what the user owns.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import Project, Resume


async def workspace_brief(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: UUID,
) -> str:
    async with sessionmaker() as s:
        n_projects = (
            await s.execute(
                select(func.count(Project.id)).where(Project.user_id == user_id)
            )
        ).scalar_one()
        n_resumes = (
            await s.execute(
                select(func.count(Resume.id)).where(Resume.user_id == user_id)
            )
        ).scalar_one()
        top_projects = (
            await s.execute(
                select(Project.name)
                .where(Project.user_id == user_id, Project.status == "ready")
                .order_by(Project.created_at.desc())
                .limit(3)
            )
        ).scalars().all()
    if n_projects == 0 and n_resumes == 0:
        return ""
    bits = [f"{n_projects} project(s)", f"{n_resumes} resume(s)"]
    if top_projects:
        bits.append("recent: " + ", ".join(top_projects))
    return "; ".join(bits)
