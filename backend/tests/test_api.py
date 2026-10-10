"""REST 接口与鉴权。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import (
    RequestTemplate,
    SyncAppResult,
    SyncSummary,
    TrustedIpCheckSummary,
    WeComApp,
    WeComLoginState,
)
from app.wecom.admin_browser import WeComAdminError
from app.passwords import hash_password
from app.security import create_session_token

SECRET_KEY = "api-test-secret"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin-pass-123"

VALID_CURL = (
    "curl 'https://work.weixin.qq.com/wework_admin/agentSetting/save?agentid=1230002' "
    "-H 'Content-Type: application/json' "
    "--data-raw '{\"agentid\":1230002,\"trusted_ip_list\":[\"203.0.113.10\"]}'"
)


class FakeWeComSession:
    """只实现接口用到的动作，避免测试启动真实浏览器。"""

    def __init__(self) -> None:
        self._state = WeComLoginState(status="idle", updated_at=datetime.now(timezone.utc))

    def login_state(self) -> WeComLoginState:
        return self._state

    async def start_login(self) -> WeComLoginState:
        self._state = WeComLoginState(
            status="waiting_scan",
            qr_png_base64="ZmFrZS1xcg==",
            message="请使用企业微信扫码",
            updated_at=datetime.now(timezone.utc),
        )
        return self._state

    async def discover_apps(self) -> list[WeComApp]:
        return [WeComApp(agent_id="1230002", name="客服系统")]


class StubSyncService:
    """同步接口返回固定结果，不触发网络与浏览器。"""

    def __init__(self) -> None:
        self.force_flags: list[bool] = []
        self.refresh_error: str | None = None

    async def sync(self, *, force: bool = False) -> SyncSummary:
        self.force_flags.append(force)
        now = datetime.now(timezone.utc)
        return SyncSummary(
            started_at=now,
            finished_at=now,
            public_ip="8.8.8.8",
            status="ok",
            message="已覆盖 1/1 个应用的可信 IP",
            results=[SyncAppResult(agent_id="1230002", name="客服系统", success=True, message="已覆盖")],
        )

    async def refresh_trusted_ips(self) -> TrustedIpCheckSummary:
        if self.refresh_error is not None:
            raise WeComAdminError(self.refresh_error)
        return TrustedIpCheckSummary(
            checked_at=datetime.now(timezone.utc),
            total=1,
            failed=0,
            message="已读取 1/1 个应用的当前可信 IP",
        )


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        frontend_dir=tmp_path / "missing-frontend",
        secret_key=SECRET_KEY,
        auto_sync_enabled=False,
        sync_interval_seconds=3600,
    )
    application = create_app(settings)
    application.state.wecom_session = FakeWeComSession()
    application.state.sync_service = StubSyncService()
    application.state.storage.create_admin_if_absent(
        ADMIN_USERNAME, hash_password(ADMIN_PASSWORD)
    )
    with TestClient(application) as test_client:
        token = create_session_token(SECRET_KEY, 600, subject=ADMIN_USERNAME)
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


def test_health_endpoint_needs_no_session(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_requires_session(client):
    del client.headers["Authorization"]

    response = client.get("/api/state")

    assert response.status_code == 401


def test_dashboard_state_returns_expected_sections(client):
    response = client.get("/api/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ikuai"]["configured"] is False
    assert payload["template_configured"] is False
    assert payload["sync_settings"]["interval_seconds"] == 3600
    assert payload["apps"] == []


def test_login_start_returns_qr_placeholder(client):
    response = client.post("/api/auth/wecom/login")

    assert response.status_code == 200
    assert response.json()["status"] == "waiting_scan"
    assert response.json()["qr_png_base64"] == "ZmFrZS1xcg=="


def test_ikuai_settings_round_trip_masks_password(client):
    save_response = client.put(
        "/api/ikuai/settings",
        json={"base_url": "192.168.1.1", "username": "admin", "password": "secret"},
    )

    assert save_response.status_code == 200
    assert save_response.json()["base_url"] == "http://192.168.1.1"
    assert save_response.json()["password_set"] is True

    read_response = client.get("/api/ikuai/settings")
    assert read_response.json()["configured"] is True
    assert "password" not in read_response.json()


def test_template_parse_and_save(client):
    parse_response = client.post("/api/wecom/template/parse", json={"curl": VALID_CURL})

    assert parse_response.status_code == 200
    template = parse_response.json()["template"]
    assert "{ip}" in template["body"]
    assert "{agent_id}" in template["url"]

    save_response = client.put("/api/wecom/template", json=template)
    assert save_response.status_code == 200

    read_response = client.get("/api/wecom/template")
    assert read_response.json()["configured"] is True


def test_template_save_rejects_missing_ip_placeholder(client):
    invalid = RequestTemplate(method="POST", url="https://example.com/save", body='{"ip":"1.1.1.1"}')

    response = client.put("/api/wecom/template", json=invalid.model_dump())

    assert response.status_code == 400
    assert "{ip}" in response.json()["detail"]


def test_read_template_parse_and_save(client):
    curl = (
        "curl 'https://work.weixin.qq.com/wework_admin/apps/getIpConfig"
        "?app_id=5629500000000001&f=json' -H 'accept: application/json'"
    )

    parse_response = client.post("/api/wecom/read-template/parse", json={"curl": curl})

    assert parse_response.status_code == 200
    template = parse_response.json()["template"]
    assert "{app_id}" in template["url"]

    save_response = client.put("/api/wecom/read-template", json=template)
    assert save_response.status_code == 200

    assert client.get("/api/wecom/read-template").json()["configured"] is True
    assert client.get("/api/wecom/template").json()["configured"] is False


def test_read_template_save_rejects_missing_app_placeholder(client):
    invalid = RequestTemplate(method="GET", url="https://example.com/app/info")

    response = client.put("/api/wecom/read-template", json=invalid.model_dump())

    assert response.status_code == 400
    assert "无法逐个应用读取" in response.json()["detail"]


def test_refresh_trusted_ips_returns_updated_apps(client):
    client.put("/api/wecom/apps/manual", json={"text": "1230006,客服系统"})

    response = client.post("/api/sync/refresh-trusted-ips")

    assert response.status_code == 200
    assert "已读取 1/1" in response.json()["message"]
    assert response.json()["apps"][0]["agent_id"] == "1230006"


def test_refresh_trusted_ips_reports_wecom_error(client):
    client.app.state.sync_service.refresh_error = "尚未录制「读取可信 IP 模板」，无法读取当前可信 IP"

    response = client.post("/api/sync/refresh-trusted-ips")

    assert response.status_code == 502
    assert "读取可信 IP 模板" in response.json()["detail"]


def test_manual_app_import(client):
    response = client.put("/api/wecom/apps/manual", json={"text": "1230001,订单系统\n1230002 客服系统"})

    assert response.status_code == 200
    assert len(response.json()["apps"]) == 2
    assert client.get("/api/wecom/apps").json()["apps"][1]["name"] == "客服系统"


def test_save_console_app_id_for_existing_app(client):
    client.put("/api/wecom/apps/manual", json={"text": "1230006,客服系统"})

    response = client.put(
        "/api/wecom/apps/1230006/console-app-id", json={"console_app_id": "5629500000000001"}
    )

    assert response.status_code == 200
    assert response.json()["apps"][0]["console_app_id"] == "5629500000000001"


def test_save_console_app_id_rejects_non_numeric_value(client):
    client.put("/api/wecom/apps/manual", json={"text": "1230006,客服系统"})

    response = client.put(
        "/api/wecom/apps/1230006/console-app-id", json={"console_app_id": "not-a-number"}
    )

    assert response.status_code == 400


def test_save_console_app_id_rejects_unknown_app(client):
    response = client.put(
        "/api/wecom/apps/999999/console-app-id", json={"console_app_id": "5629500000000001"}
    )

    assert response.status_code == 404


def test_discover_apps_uses_session(client):
    response = client.post("/api/wecom/apps/discover")

    assert response.status_code == 200
    assert response.json()["apps"][0]["agent_id"] == "1230002"


def test_sync_run_returns_summary_and_forwards_force_flag(client):
    response = client.post("/api/sync/run", json={"force": True})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert client.app.state.sync_service.force_flags == [True]


def test_sync_events_returns_stored_history(client):
    client.post("/api/sync/run", json={"force": False})
    response = client.get("/api/sync/events?limit=5")

    assert response.status_code == 200
    assert response.json() == []
