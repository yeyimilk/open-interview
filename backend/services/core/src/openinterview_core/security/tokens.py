from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt


class TokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    user_id: UUID
    is_admin: bool
    typ: str  # "access" | "refresh"
    exp: datetime


class TokenIssuer:
    def __init__(self, secret: str, access_ttl_s: int, refresh_ttl_s: int) -> None:
        self._secret = secret
        self._access_ttl = access_ttl_s
        self._refresh_ttl = refresh_ttl_s

    def _encode(self, user_id: UUID, is_admin: bool, typ: str, ttl_s: int) -> tuple[str, datetime]:
        exp = datetime.now(timezone.utc) + timedelta(seconds=ttl_s)
        payload = {
            "sub": str(user_id),
            "adm": is_admin,
            "typ": typ,
            "exp": int(exp.timestamp()),
        }
        token = jwt.encode(payload, self._secret, algorithm="HS256")
        return token, exp

    def issue_access(self, user_id: UUID, is_admin: bool) -> tuple[str, datetime]:
        return self._encode(user_id, is_admin, "access", self._access_ttl)

    def issue_refresh(self, user_id: UUID, is_admin: bool) -> tuple[str, datetime]:
        return self._encode(user_id, is_admin, "refresh", self._refresh_ttl)

    def decode(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(token, self._secret, algorithms=["HS256"])
        except jwt.PyJWTError as e:
            raise TokenError(str(e)) from e
        try:
            return TokenClaims(
                user_id=UUID(payload["sub"]),
                is_admin=bool(payload.get("adm", False)),
                typ=str(payload["typ"]),
                exp=datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc),
            )
        except (KeyError, ValueError) as e:
            raise TokenError(f"malformed token: {e}") from e
