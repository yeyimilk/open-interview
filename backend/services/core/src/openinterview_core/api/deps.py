"""FastAPI dependencies. Single place for auth, DB, and service wiring."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import User

from ..domain.auth import AuthService
from ..infra.db import get_session_dep
from ..infra.db.user_repository import SqlUserRepository
from ..security import TokenError, TokenIssuer

_bearer = HTTPBearer(auto_error=False)


def get_token_issuer(request: Request) -> TokenIssuer:
    return request.app.state.token_issuer


def get_auth_service(
    session: AsyncSession = Depends(get_session_dep),
    issuer: TokenIssuer = Depends(get_token_issuer),
) -> AuthService:
    repo = SqlUserRepository(session)
    return AuthService(users=repo, tokens=issuer)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session_dep),
    issuer: TokenIssuer = Depends(get_token_issuer),
) -> User:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing token")
    try:
        claims = issuer.decode(creds.credentials)
    except TokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    if claims.typ != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not an access token")
    user = await SqlUserRepository(session).get_by_id(claims.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    return user
