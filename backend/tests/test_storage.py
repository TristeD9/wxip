"""SQLite 存储读写。"""

from datetime import datetime, timezone

import pytest

from app.models import (
    IKuaiSettings,
    PublicIpObservation,
    RequestTemplate,
    SyncAppResult,
    SyncSettings,
    SyncSummary,
    WeComApp,
)
from app.storage import AppStorage


@pytest.fixture
def storage(tmp_path):
    store = AppStorage(tmp_path / "app.sqlite3")
    store.initialize()
    return store


def test_ikuai_settings_round_trip(storage):
    settings = IKuaiSettings(base_url="http://192.168.1.1", username="admin", password="secret")

    storage.save_ikuai_settings(settings)

    assert storage.get_ikuai_settings() == settings


def test_request_template_round_trip(storage):
    template = RequestTemplate(method="POST", url="https://example.com/{agent_id}", body='["{ip}"]')

    storage.save_request_template(template)

    assert storage.get_request_template() == template


def test_sync_settings_fall_back_to_default(storage):
    stored = storage.get_sync_settings(SyncSettings(auto_enabled=False, interval_seconds=120))

    assert stored.auto_enabled is False
    assert stored.interval_seconds == 120


def test_replace_apps_then_update_result(storage):
    storage.replace_wecom_apps([WeComApp(agent_id="1230002", name="客服系统")])

    storage.update_app_sync_result(
        "1230002", synced_ip="8.8.8.8", synced_at="2026-01-01T00:00:00+00:00", error=None
    )

    apps = storage.list_wecom_apps()
    assert len(apps) == 1
    assert apps[0].last_synced_ip == "8.8.8.8"
    assert apps[0].last_error is None


def test_replace_apps_keeps_console_app_id(storage):
    storage.replace_wecom_apps(
        [WeComApp(agent_id="1230006", name="客服系统", console_app_id="5629500000000001")]
    )

    apps = storage.list_wecom_apps()

    assert apps[0].console_app_id == "5629500000000001"


def test_update_app_console_id(storage):
    storage.replace_wecom_apps([WeComApp(agent_id="1230006", name="客服系统")])

    storage.update_app_console_id("1230006", "5629500000000001")

    assert storage.list_wecom_apps()[0].console_app_id == "5629500000000001"


def test_admin_accounts_start_empty(storage):
    assert storage.count_admins() == 0
    assert storage.list_admin_usernames() == []


def test_create_admin_only_once(storage):
    assert storage.create_admin_if_absent("admin", "hash-one") is True

    assert storage.create_admin_if_absent("second", "hash-two") is False
    assert storage.list_admin_usernames() == ["admin"]


def test_get_admin_returns_none_for_unknown_username(storage):
    assert storage.get_admin("ghost") is None


def test_update_admin_password(storage):
    storage.create_admin_if_absent("admin", "hash-one")

    updated = storage.update_admin_password("admin", "hash-two")

    admin = storage.get_admin("admin")
    assert updated is True
    assert admin is not None
    assert admin.password_hash == "hash-two"


def test_update_admin_password_reports_missing_account(storage):
    assert storage.update_admin_password("ghost", "hash") is False


def test_delete_admin_supports_single_and_all(storage):
    storage.create_admin_if_absent("admin", "hash-one")

    assert storage.delete_admin("ghost") == 0
    assert storage.delete_admin("admin") == 1
    assert storage.count_admins() == 0


def test_latest_public_ip_returns_most_recent_observation(storage):
    storage.record_public_ip(
        PublicIpObservation(ip="1.1.1.1", source="ikuai", checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    )
    storage.record_public_ip(
        PublicIpObservation(ip="8.8.8.8", source="ikuai", checked_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    )

    latest = storage.latest_public_ip()

    assert latest is not None
    assert latest.ip == "8.8.8.8"


def test_sync_summary_round_trip_keeps_results(storage):
    summary = SyncSummary(
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        finished_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        public_ip="8.8.8.8",
        status="ok",
        message="已覆盖 1/1 个应用的可信 IP",
        results=[SyncAppResult(agent_id="1230002", name="客服系统", success=True, message="已覆盖为 8.8.8.8")],
    )

    storage.record_sync_summary(summary)
    stored = storage.list_sync_summaries(limit=10)

    assert len(stored) == 1
    assert stored[0].results[0].agent_id == "1230002"
    assert stored[0].status == "ok"

