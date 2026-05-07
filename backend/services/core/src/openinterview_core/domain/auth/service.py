"""Auth service: pure domain logic. No HTTP, no SQL."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from openinterview_db import User

from ...security import TokenIssuer, hash_password, verify_password
from .repository import UserRepository


class AuthError(Exception):
    pass


class EmailAlreadyExists(AuthError):
    pass


class InvalidCredentials(AuthError):
    pass


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        tokens: TokenIssuer,
        bootstrap_admin_email: str | None = None,
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._bootstrap_admin_email = (
            bootstrap_admin_email.strip().lower() if bootstrap_admin_email else None
        )

    async def register(self, *, email: str, password: str, display_name: str) -> User:
        email_norm = email.strip().lower()
        if await self._users.get_by_email(email_norm) is not None:
            raise EmailAlreadyExists(email_norm)
        is_first_user = await self._users.count_users() == 0
        is_bootstrap_admin = email_norm == self._bootstrap_admin_email
        return await self._users.create(
            email=email_norm,
            password_hash=hash_password(password),
            display_name=display_name.strip(),
            is_admin=is_first_user or is_bootstrap_admin,
        )

    async def login(self, *, email: str, password: str) -> tuple[User, IssuedTokens]:
        user = await self._users.get_by_email(email.strip().lower())
        if user is None or not verify_password(user.password_hash, password):
            raise InvalidCredentials()
        return user, self._issue_tokens(user.id, user.is_admin)

    async def refresh(self, user_id: UUID) -> IssuedTokens:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise InvalidCredentials()
        return self._issue_tokens(user.id, user.is_admin)

    def _issue_tokens(self, user_id: UUID, is_admin: bool) -> IssuedTokens:
        access, access_exp = self._tokens.issue_access(user_id, is_admin)
        refresh, refresh_exp = self._tokens.issue_refresh(user_id, is_admin)
        return IssuedTokens(
            access_token=access,
            access_expires_at=access_exp,
            refresh_token=refresh,
            refresh_expires_at=refresh_exp,
        )
