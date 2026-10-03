"""管理员密码哈希。"""

from app.passwords import (
    MIN_PASSWORD_LENGTH,
    check_password_strength,
    hash_password,
    verify_password,
)

PASSWORD = "s3cret-passphrase"


def test_hash_and_verify_round_trip():
    stored = hash_password(PASSWORD)

    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password(PASSWORD, stored) is True


def test_verify_rejects_wrong_password():
    stored = hash_password(PASSWORD)

    assert verify_password("wrong-password", stored) is False


def test_hash_uses_unique_salt_per_call():
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_verify_rejects_malformed_hash():
    assert verify_password(PASSWORD, "not-a-hash") is False
    assert verify_password(PASSWORD, "pbkdf2_sha256$abc$def$ghi") is False


def test_check_password_strength_rejects_short_password():
    short = "a" * (MIN_PASSWORD_LENGTH - 1)

    assert check_password_strength(short) is not None


def test_check_password_strength_rejects_blank_password():
    assert check_password_strength("        ") is not None


def test_check_password_strength_accepts_valid_password():
    assert check_password_strength("a" * MIN_PASSWORD_LENGTH) is None

