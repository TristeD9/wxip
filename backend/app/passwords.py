"""管理员密码哈希：PBKDF2-HMAC-SHA256，只依赖标准库。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PBKDF2_ITERATIONS = 200_000
MIN_PASSWORD_LENGTH = 8

_ALGORITHM = "sha256"
_SALT_BYTES = 16
_HASH_PREFIX = f"pbkdf2_{_ALGORITHM}"


def hash_password(password: str) -> str:
    """返回 ``pbkdf2_sha256$迭代次数$盐$哈希`` 形式的可存储字符串。"""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(_ALGORITHM, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "$".join(
        [
            _HASH_PREFIX,
            str(PBKDF2_ITERATIONS),
            _encode(salt),
            _encode(digest),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """校验密码；哈希格式不合法时返回 False，不抛异常。"""
    parts = stored_hash.split("$")
    if len(parts) != 4 or parts[0] != _HASH_PREFIX:
        return False
    try:
        iterations = int(parts[1])
        salt = _decode(parts[2])
        expected = _decode(parts[3])
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac(_ALGORITHM, password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def check_password_strength(password: str) -> str | None:
    """返回不合规原因，合规时返回 None。"""
    if not password.strip():
        return "密码不能为空"
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"密码至少需要 {MIN_PASSWORD_LENGTH} 位"
    return None


def _encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _decode(encoded: str) -> bytes:
    return base64.b64decode(encoded.encode("ascii"), validate=True)

