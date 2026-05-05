from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest

from openinterview_realtime.domain.ticket import TicketError, verify_ticket


SECRET = "test-secret"


def _make_ticket(*, exp_offset: int = 60, **claims) -> str:
    payload = {
        "sub": str(uuid4()),
        "sid": str(uuid4()),
        "mode": "interviewer",
        "exp": int(time.time()) + exp_offset,
        **claims,
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


def test_verify_ticket_ok() -> None:
    sub = str(uuid4())
    sid = str(uuid4())
    t = _make_ticket(sub=sub, sid=sid)
    claims = verify_ticket(t, SECRET)
    assert str(claims.user_id) == sub
    assert str(claims.session_id) == sid
    assert claims.mode == "interviewer"


def test_verify_ticket_expired() -> None:
    t = _make_ticket(exp_offset=-10)
    with pytest.raises(TicketError):
        verify_ticket(t, SECRET)


def test_verify_ticket_bad_signature() -> None:
    t = _make_ticket()
    with pytest.raises(TicketError):
        verify_ticket(t, "wrong-secret")
