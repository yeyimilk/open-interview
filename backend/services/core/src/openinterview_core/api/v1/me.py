from __future__ import annotations

from fastapi import APIRouter, Depends

from openinterview_db import User
from openinterview_schemas import UserOut

from ..deps import get_current_user

router = APIRouter(prefix="/me", tags=["me"])


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
