"""会话令牌签名与过期校验。"""

from app.security import create_session_token, read_session_token

SECRET = "unit-test-secret"


def test_read_session_token_returns_subject_for_fresh_token():
    token = create_session_token(SECRET, ttl_seconds=60, subject="admin", now=1_000)

    assert read_session_token(SECRET, token, now=1_030) == "admin"


def test_read_session_token_rejects_expired_token():
    token = create_session_token(SECRET, ttl_seconds=60, subject="admin", now=1_000)

    assert read_session_token(SECRET, token, now=1_061) is None


def test_read_session_token_rejects_tampered_token():
    token = create_session_token(SECRET, ttl_seconds=60, subject="admin", now=1_000)
    tampered = f"{token[:-2]}xx"

    assert read_session_token(SECRET, tampered, now=1_010) is None


def test_read_session_token_rejects_other_secret():
    token = create_session_token(SECRET, ttl_seconds=60, subject="admin", now=1_000)

    assert read_session_token("another-secret", token, now=1_010) is None


def test_read_session_token_rejects_malformed_value():
    assert read_session_token(SECRET, "not-a-token", now=1_010) is None
    assert read_session_token(SECRET, "", now=1_010) is None

