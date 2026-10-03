"""管理员初始化、登录、改密与鉴权。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SECRET_KEY = "admin-auth-test-secret"
USERNAME = "admin"
PASSWORD = "admin-pass-123"
NEW_PASSWORD = "new-admin-pass-456"


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        frontend_dir=tmp_path / "missing-frontend",
        secret_key=SECRET_KEY,
        auto_sync_enabled=False,
        sync_interval_seconds=3600,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def create_admin(client: TestClient) -> str:
    response = client.post(
        "/api/auth/setup",
        json={"username": USERNAME, "password": PASSWORD, "password_confirm": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_setup_status_is_false_before_initialization(client):
    response = client.get("/api/auth/setup/status")

    assert response.status_code == 200
    assert response.json() == {"initialized": False}


def test_setup_creates_admin_and_returns_token(client):
    token = create_admin(client)

    assert client.get("/api/auth/setup/status").json() == {"initialized": True}
    assert client.get("/api/auth/me", headers=auth_headers(token)).json() == {"username": USERNAME}


def test_setup_rejects_second_call(client):
    create_admin(client)

    response = client.post(
        "/api/auth/setup",
        json={"username": "other", "password": PASSWORD, "password_confirm": PASSWORD},
    )

    assert response.status_code == 409


def test_setup_rejects_short_password(client):
    response = client.post(
        "/api/auth/setup",
        json={"username": USERNAME, "password": "short", "password_confirm": "short"},
    )

    assert response.status_code == 400
    assert "8" in response.json()["detail"]


def test_setup_rejects_mismatched_confirmation(client):
    response = client.post(
        "/api/auth/setup",
        json={"username": USERNAME, "password": PASSWORD, "password_confirm": PASSWORD + "x"},
    )

    assert response.status_code == 400
    assert "不一致" in response.json()["detail"]


def test_login_returns_token_for_valid_credentials(client):
    create_admin(client)

    response = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})

    assert response.status_code == 200
    assert response.json()["username"] == USERNAME
    assert response.json()["token"]


def test_login_rejects_wrong_password(client):
    create_admin(client)

    response = client.post("/api/auth/login", json={"username": USERNAME, "password": "nope"})

    assert response.status_code == 401


def test_login_locks_after_repeated_failures(client):
    create_admin(client)
    for _ in range(5):
        client.post("/api/auth/login", json={"username": USERNAME, "password": "nope"})

    response = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})

    assert response.status_code == 429


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_token_of_deleted_admin_is_rejected(client):
    token = create_admin(client)
    client.app.state.storage.delete_admin()

    response = client.get("/api/auth/me", headers=auth_headers(token))

    assert response.status_code == 401


def test_change_password_requires_correct_current_password(client):
    token = create_admin(client)

    response = client.post(
        "/api/auth/password",
        json={
            "current_password": "wrong",
            "new_password": NEW_PASSWORD,
            "new_password_confirm": NEW_PASSWORD,
        },
        headers=auth_headers(token),
    )

    assert response.status_code == 400


def test_change_password_rejects_mismatched_confirmation(client):
    token = create_admin(client)

    response = client.post(
        "/api/auth/password",
        json={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "new_password_confirm": NEW_PASSWORD + "x",
        },
        headers=auth_headers(token),
    )

    assert response.status_code == 400


def test_change_password_switches_credentials(client):
    token = create_admin(client)
    client.post(
        "/api/auth/password",
        json={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "new_password_confirm": NEW_PASSWORD,
        },
        headers=auth_headers(token),
    )

    old_login = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    new_login = client.post(
        "/api/auth/login", json={"username": USERNAME, "password": NEW_PASSWORD}
    )

    assert old_login.status_code == 401
    assert new_login.status_code == 200

