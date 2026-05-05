"""Verifies short-lived HMAC tickets minted by `core` for WS upgrades.

Tickets are JWTs (HS256) with claims:
    sub  : user id (uuid str)
    sid  : chat session id (uuid str)
    mode : "interviewer"
    exp  : unix timestamp (int)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

import jwt


class TicketError(Exception):
    pass


@dataclass(frozen=True)
class TicketClaims:
    user_id: UUID
    session_id: UUID
    mode: str
    exp: int


def verify_ticket(token: str, secret: str) -> TicketClaims:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise TicketError(f"invalid ticket: {e}") from e
    try:
        exp = int(payload["exp"])
        if exp < int(time.time()):
            raise TicketError("ticket expired")
        return TicketClaims(
            user_id=UUID(str(payload["sub"])),
            session_id=UUID(str(payload["sid"])),
            mode=str(payload.get("mode", "interviewer")),
            exp=exp,
        )
    except (KeyError, ValueError) as e:
        raise TicketError(f"malformed ticket: {e}") from e
