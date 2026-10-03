"""面板会话令牌：用 HMAC 签名，不引入额外依赖。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def create_session_token(
    secret_key: str, ttl_seconds: int, *, subject: str, now: float | None = None
) -> str:
    """签发一个带过期时间的会话令牌。

    Args:
        secret_key: 服务端签名密钥。
        ttl_seconds: 令牌有效期，单位秒。
        subject: 令牌归属的管理员用户名。
        now: 便于测试注入的当前时间戳。

    Returns:
        base64 编码的 ``payload.signature`` 令牌。
    """
    issued_at = int(now if now is not None else time.time())
    payload = json.dumps(
        {"sub": subject, "iat": issued_at, "exp": issued_at + ttl_seconds}, separators=(",", ":")
    )
    encoded_payload = _base64_url_encode(payload.encode("utf-8"))
    signature = _sign(secret_key, encoded_payload)
    return f"{encoded_payload}.{signature}"


def read_session_token(secret_key: str, token: str, *, now: float | None = None) -> str | None:
    """校验令牌并返回其中的管理员用户名，失败返回 None。"""
    if not token or "." not in token:
        return None
    encoded_payload, _, signature = token.partition(".")
    if not hmac.compare_digest(signature, _sign(secret_key, encoded_payload)):
        return None
    try:
        payload = json.loads(_base64_url_decode(encoded_payload).decode("utf-8"))
        expires_at = int(payload["exp"])
        subject = str(payload["sub"])
    except (ValueError, KeyError, TypeError):
        return None
    if not subject or expires_at <= int(now if now is not None else time.time()):
        return None
    return subject


def _sign(secret_key: str, encoded_payload: str) -> str:
    digest = hmac.new(secret_key.encode("utf-8"), encoded_payload.encode("utf-8"), hashlib.sha256)
    return _base64_url_encode(digest.digest())


def _base64_url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _base64_url_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)
