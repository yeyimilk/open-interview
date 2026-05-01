from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from openinterview_schemas import LoginRequest, RegisterRequest, TokenPair, UserOut

from ...domain.auth import AuthService, EmailAlreadyExists, InvalidCredentials
from ...security.tokens import TokenError
from ..deps import get_auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, auth: AuthService = Depends(get_auth_service)) -> UserOut:
    try:
        user = await auth.register(
            email=req.email, password=req.password, display_name=req.display_name
        )
    except EmailAlreadyExists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tier=user.tier,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenPair)
async def login(req: LoginRequest, auth: AuthService = Depends(get_auth_service)) -> TokenPair:
    try:
        _, tokens = await auth.login(email=req.email, password=req.password)
    except InvalidCredentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    return TokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        access_expires_at=tokens.access_expires_at,
        refresh_expires_at=tokens.refresh_expires_at,
    )


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
) -> TokenPair:
    issuer = request.app.state.token_issuer
    try:
        claims = issuer.decode(body.refresh_token)
    except TokenError:
        raise HTTPException(status_code=401, detail="invalid refresh token")
    if claims.typ != "refresh":
        raise HTTPException(status_code=401, detail="not a refresh token")
    tokens = await auth.refresh(claims.user_id, claims.is_admin)
    return TokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        access_expires_at=tokens.access_expires_at,
        refresh_expires_at=tokens.refresh_expires_at,
    )
