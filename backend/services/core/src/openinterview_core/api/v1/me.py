from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import User
from openinterview_schemas import InterviewPreferenceIn, InterviewPreferenceOut, UserOut

from ...domain.users import DataPortabilityService
from ...infra.db import get_session_dep
from ...infra.db.common_kb_repository import SqlCommonKBRepository
from ..deps import get_current_user

router = APIRouter(prefix="/me", tags=["me"])


class WipeDataRequest(BaseModel):
    confirmation: str


@router.get("", response_model=UserOut)
async def whoami(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tier=user.tier,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )


@router.get("/export")
async def export_my_data(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> Response:
    data = await DataPortabilityService(
        session=session,
        blob=request.app.state.blob,
        vector_store=request.app.state.vector_store,
    ).export_user_zip(user_id=user.id)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"open-interview-export-{stamp}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-store",
        },
    )


@router.post("/wipe")
async def wipe_my_data(
    body: WipeDataRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> dict:
    if body.confirmation != "WIPE":
        raise HTTPException(status_code=400, detail="confirmation must be WIPE")
    return await DataPortabilityService(
        session=session,
        blob=request.app.state.blob,
        vector_store=request.app.state.vector_store,
    ).wipe_user_data(user_id=user.id)


@router.get("/interview-preferences", response_model=InterviewPreferenceOut)
async def get_interview_preferences(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> InterviewPreferenceOut:
    row = await SqlCommonKBRepository(session).get_user_preferences(user_id=user.id)
    if row is None:
        return InterviewPreferenceOut(user_id=user.id)
    return InterviewPreferenceOut(
        id=row.id,
        user_id=row.user_id,
        target_company=row.target_company,
        category_weights=row.category_weights,
        languages=row.languages or [],
        interview_style=row.interview_style,
        include_company_style=row.include_company_style,
        created_at=row.created_at,
    )


@router.put("/interview-preferences", response_model=InterviewPreferenceOut)
async def put_interview_preferences(
    body: InterviewPreferenceIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> InterviewPreferenceOut:
    row = await SqlCommonKBRepository(session).upsert_user_preferences(
        user_id=user.id,
        target_company=body.target_company,
        category_weights=body.category_weights,
        languages=body.languages,
        interview_style=body.interview_style,
        include_company_style=body.include_company_style,
    )
    return InterviewPreferenceOut(
        id=row.id,
        user_id=row.user_id,
        target_company=row.target_company,
        category_weights=row.category_weights,
        languages=row.languages or [],
        interview_style=row.interview_style,
        include_company_style=row.include_company_style,
        created_at=row.created_at,
    )
