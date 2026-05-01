from uuid import uuid4

from openinterview_core.security import SecretBox, TokenIssuer, hash_password, verify_password


def test_password_roundtrip() -> None:
    h = hash_password("hunter2-very-strong")
    assert verify_password(h, "hunter2-very-strong") is True
    assert verify_password(h, "wrong") is False


def test_token_roundtrip() -> None:
    issuer = TokenIssuer("test-secret", access_ttl_s=60, refresh_ttl_s=120)
    uid = uuid4()
    tok, _ = issuer.issue_access(uid, is_admin=False)
    claims = issuer.decode(tok)
    assert claims.user_id == uid
    assert claims.typ == "access"


def test_secret_box_roundtrip() -> None:
    box = SecretBox("master-key-for-tests-please-change!")
    blob = box.encrypt("sk-abc123")
    assert box.decrypt(blob) == "sk-abc123"
