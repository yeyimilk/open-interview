from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import User
from openinterview_schemas import CommonKBItemOut, CommonKBSpaceOut, CompanyInterviewProfileOut

from ...infra.db import get_session_dep
from ...infra.db.common_kb_repository import SqlCommonKBRepository
from ..deps import get_current_user
from .admin_kb import _item_out, _space_out

router = APIRouter(prefix="/kb", tags=["kb"])


@router.get("/spaces", response_model=list[CommonKBSpaceOut])
async def list_public_spaces(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[CommonKBSpaceOut]:
    return [_space_out(r) for r in await SqlCommonKBRepository(session).list_spaces(enabled_only=True)]


@router.get("/company-profiles", response_model=list[CompanyInterviewProfileOut])
async def list_company_profiles(
    query: str | None = None,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[CompanyInterviewProfileOut]:
    rows = await SqlCommonKBRepository(session).list_company_profiles(query=query)
    return [
        CompanyInterviewProfileOut(
            id=r.id, company_key=r.company_key, company=r.company,
            role_family=r.role_family, category_weights=r.category_weights,
            language_preferences=r.language_preferences,
            round_patterns=r.round_patterns, confidence=r.confidence,
            source_refs=r.source_refs, item_count=r.item_count,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/items", response_model=list[CommonKBItemOut])
async def list_public_items(
    space: str | None = None,
    tag: str | None = None,
    company: str | None = None,
    category: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> list[CommonKBItemOut]:
    repo = SqlCommonKBRepository(session)
    rows = await repo.list_items(space_key=space, tag=tag, company=company, category=category)
    return [await _item_out(repo, r) for r in rows]
