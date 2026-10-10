"""同步编排逻辑。"""

from datetime import datetime, timezone

import pytest

from app.models import (
    IKuaiSettings,
    PublicIpObservation,
    RequestTemplate,
    WeComApp,
)
from app.services.public_ip import PublicIpError
from app.services.sync_service import SyncService
from app.storage import AppStorage
from app.wecom.admin_browser import WeComAdminError


class FakeResolver:
    def __init__(self, *, ip: str = "8.8.8.8", error: str | None = None) -> None:
        self.ip = ip
        self.error = error

    async def resolve(self, ikuai_settings: IKuaiSettings | None) -> PublicIpObservation:
        if self.error:
            raise PublicIpError(self.error)
        return PublicIpObservation(ip=self.ip, source="ikuai", checked_at=datetime.now(timezone.utc))


class FakeWeComSession:
    def __init__(
        self,
        *,
        failing_agent_ids: set[str] | None = None,
        logged_in: bool = True,
        failure_message: str = "企业微信返回 HTTP 500",
    ) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.failing_agent_ids = failing_agent_ids or set()
        self.logged_in = logged_in
        self.failure_message = failure_message

    async def ensure_logged_in(self) -> None:
        if not self.logged_in:
            raise WeComAdminError("尚未登录企业微信管理后台，请先扫码登录")

    async def replay_request(
        self, template: RequestTemplate, *, agent_id: str, app_id: str, ip: str
    ) -> str:
        self.calls.append((agent_id, app_id, ip))
        if agent_id in self.failing_agent_ids:
            raise WeComAdminError(self.failure_message)
        return '{"errcode":0}'


@pytest.fixture
def storage(tmp_path):
    store = AppStorage(tmp_path / "app.sqlite3")
    store.initialize()
    return store


def prepare_storage(storage, apps=None):
    storage.save_ikuai_settings(IKuaiSettings(base_url="http://192.168.1.1", password="secret"))
    storage.save_request_template(
        RequestTemplate(method="POST", url="https://example.com/{agent_id}", body='["{ip}"]')
    )
    storage.replace_wecom_apps(apps or [WeComApp(agent_id="1230002", name="客服系统")])


async def test_sync_overwrites_all_apps_with_latest_ip(storage):
    prepare_storage(
        storage,
        apps=[
            WeComApp(agent_id="1230001", name="订单系统"),
            WeComApp(agent_id="1230002", name="客服系统"),
        ],
    )
    wecom_session = FakeWeComSession()
    service = SyncService(storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_session)

    summary = await service.sync()

    assert summary.status == "ok"
    assert summary.public_ip == "9.9.9.9"
    assert len(summary.results) == 2
    assert wecom_session.calls == [
        ("1230001", "", "9.9.9.9"),
        ("1230002", "", "9.9.9.9"),
    ]
    assert all(app.last_synced_ip == "9.9.9.9" for app in storage.list_wecom_apps())


async def test_sync_rewrites_even_when_ip_unchanged(storage):
    """公网 IP 没变也要重写：本地记录不代表企业微信里的真实状态。"""
    prepare_storage(storage)
    wecom_session = FakeWeComSession()
    service = SyncService(storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_session)
    await service.sync()

    second = await service.sync()

    assert second.status == "ok"
    assert len(wecom_session.calls) == 2


async def test_sync_retries_apps_whose_previous_attempt_failed(storage):
    """上次写入失败的应用不能被「IP 未变化」永久跳过，必须再写一次。"""
    prepare_storage(storage)
    service = SyncService(
        storage=storage,
        resolver=FakeResolver(ip="9.9.9.9"),
        wecom_session=FakeWeComSession(failing_agent_ids={"1230002"}),
    )
    first = await service.sync()
    assert first.status == "failed"

    healthy_session = FakeWeComSession()
    recovered = await SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=healthy_session
    ).sync()

    assert recovered.status == "ok"
    assert healthy_session.calls == [("1230002", "", "9.9.9.9")]
    assert storage.list_wecom_apps()[0].last_error is None


async def test_sync_fails_when_template_missing(storage):
    storage.save_ikuai_settings(IKuaiSettings(base_url="http://192.168.1.1"))
    storage.replace_wecom_apps([WeComApp(agent_id="1230002", name="客服系统")])
    service = SyncService(
        storage=storage, resolver=FakeResolver(), wecom_session=FakeWeComSession()
    )

    summary = await service.sync()

    assert summary.status == "failed"
    assert "模板" in summary.message


async def test_sync_fails_when_resolver_fails(storage):
    prepare_storage(storage)
    service = SyncService(
        storage=storage, resolver=FakeResolver(error="全部来源失败"), wecom_session=FakeWeComSession()
    )

    summary = await service.sync()

    assert summary.status == "failed"
    assert summary.public_ip is None
    assert "全部来源失败" in summary.message


async def test_sync_records_partial_failure(storage):
    prepare_storage(
        storage,
        apps=[
            WeComApp(agent_id="1230001", name="订单系统"),
            WeComApp(agent_id="1230002", name="客服系统"),
        ],
    )
    service = SyncService(
        storage=storage,
        resolver=FakeResolver(ip="9.9.9.9"),
        wecom_session=FakeWeComSession(failing_agent_ids={"1230002"}),
    )

    summary = await service.sync()

    assert summary.status == "failed"
    assert [result.success for result in summary.results] == [True, False]
    failed_app = next(app for app in storage.list_wecom_apps() if app.agent_id == "1230002")
    assert failed_app.last_error == "企业微信返回 HTTP 500"


async def test_sync_marks_app_failed_when_wecom_rejects_request(storage):
    """企业微信用 HTTP 200 + errcode 拒绝时，不能记成同步成功。"""
    prepare_storage(storage)
    service = SyncService(
        storage=storage,
        resolver=FakeResolver(ip="9.9.9.9"),
        wecom_session=FakeWeComSession(
            failing_agent_ids={"1230002"},
            failure_message="企业微信拒绝了本次请求：errcode=301002 msg=invalid url_token",
        ),
    )

    summary = await service.sync()

    assert summary.status == "failed"
    assert summary.results[0].success is False
    assert "errcode=301002" in summary.results[0].message
    stored_app = storage.list_wecom_apps()[0]
    assert stored_app.last_synced_ip is None
    assert "errcode=301002" in stored_app.last_error


async def test_sync_fails_when_not_logged_in(storage):
    prepare_storage(storage)
    service = SyncService(
        storage=storage,
        resolver=FakeResolver(),
        wecom_session=FakeWeComSession(logged_in=False),
    )

    summary = await service.sync()

    assert summary.status == "failed"
    assert "扫码登录" in summary.message


async def test_sync_fails_when_template_needs_missing_console_app_id(storage):
    storage.save_ikuai_settings(IKuaiSettings(base_url="http://192.168.1.1"))
    storage.save_request_template(
        RequestTemplate(
            method="POST",
            url="https://example.com/saveIpConfig",
            body="app_id={app_id}&ipList%5B%5D={ip}",
        )
    )
    storage.replace_wecom_apps([WeComApp(agent_id="1230006", name="客服系统")])
    wecom_session = FakeWeComSession()
    service = SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_session
    )

    summary = await service.sync()

    assert summary.status == "failed"
    assert wecom_session.calls == []
    assert "{app_id}" in summary.results[0].message


async def test_sync_passes_console_app_id_when_known(storage):
    storage.save_ikuai_settings(IKuaiSettings(base_url="http://192.168.1.1"))
    storage.save_request_template(
        RequestTemplate(
            method="POST",
            url="https://example.com/saveIpConfig",
            body="app_id={app_id}&ipList%5B%5D={ip}",
        )
    )
    storage.replace_wecom_apps(
        [WeComApp(agent_id="1230006", name="客服系统", console_app_id="5629500000000001")]
    )
    wecom_session = FakeWeComSession()
    service = SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_session
    )

    summary = await service.sync()

    assert summary.status == "ok"
    assert wecom_session.calls == [("1230006", "5629500000000001", "9.9.9.9")]
