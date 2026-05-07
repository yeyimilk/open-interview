from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import User
from openinterview_schemas import AdminUserUpdateRequest, UserOut

from ...infra.db import get_session_dep
from ...infra.db.user_repository import SqlUserRepository
from ..deps import require_admin

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tier=user.tier,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )


@router.get("", response_model=list[UserOut])
async def list_users(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> list[UserOut]:
    users = await SqlUserRepository(session).list_users()
    return [_user_out(user) for user in users]


@router.patch("/{user_id}", response_model=UserOut)
async def update_user_role(
    user_id: UUID,
    body: AdminUserUpdateRequest,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session_dep),
) -> UserOut:
    repo = SqlUserRepository(session)
    target = await repo.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    if body.is_admin is False and target.is_admin and await repo.count_admins() <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot remove the last admin",
        )

    tier = body.tier.strip() if body.tier is not None else None
    if tier == "":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="tier is required")

    updated = await repo.update_user(
        user_id,
        tier=tier,
        is_admin=body.is_admin,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return _user_out(updated)
