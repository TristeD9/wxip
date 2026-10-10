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
    """模拟企业微信会话：列表读取、逐个模板读取与写入。"""

    def __init__(
        self,
        *,
        failing_agent_ids: set[str] | None = None,
        logged_in: bool = True,
        failure_message: str = "企业微信返回 HTTP 500",
        trusted_ips_by_agent: dict[str, list[str]] | None = None,
        listing_error_message: str | None = None,
        writes_take_effect: bool = True,
    ) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.listing_reads = 0
        self.failing_agent_ids = failing_agent_ids or set()
        self.logged_in = logged_in
        self.failure_message = failure_message
        self.trusted_ips_by_agent = trusted_ips_by_agent or {}
        self.listing_error_message = listing_error_message
        self.writes_take_effect = writes_take_effect

    async def ensure_logged_in(self) -> None:
        if not self.logged_in:
            raise WeComAdminError("尚未登录企业微信管理后台，请先扫码登录")

    async def replay_request(
        self, template: RequestTemplate, *, agent_id: str, app_id: str, ip: str
    ) -> str:
        self.calls.append((agent_id, app_id, ip))
        if agent_id in self.failing_agent_ids:
            raise WeComAdminError(self.failure_message)
        if self.writes_take_effect:
            # 模拟后台真的写进去了：之后读取会看到新值
            self.trusted_ips_by_agent[agent_id] = [ip]
        return '{"errcode":0}'

    async def read_app_trusted_ips(self) -> dict[str, list[str]]:
        self.listing_reads += 1
        if self.listing_error_message is not None:
            raise WeComAdminError(self.listing_error_message)
        return {agent_id: list(ips) for agent_id, ips in self.trusted_ips_by_agent.items()}


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


async def test_sync_skips_apps_whose_current_ip_already_matches(storage):
    """第二次同步读到值已一致，就不再写入。"""
    prepare_storage(storage)
    wecom_session = FakeWeComSession()
    service = SyncService(storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_session)
    await service.sync()

    second = await service.sync()

    assert second.status == "unchanged"
    assert "均已是 9.9.9.9" in second.message
    assert len(wecom_session.calls) == 1
    assert wecom_session.listing_reads == 3


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


async def test_sync_force_rewrites_even_when_current_ip_matches(storage):
    """force 是真正的强制覆盖：读到已经一致也重写一遍。"""
    prepare_storage(storage)
    wecom_session = FakeWeComSession()
    service = SyncService(storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_session)
    await service.sync()

    forced = await service.sync(force=True)

    assert forced.status == "ok"
    assert len(wecom_session.calls) == 2
    assert "已回读确认" in forced.results[0].message


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


async def test_sync_skips_write_when_listed_ip_already_matches(storage):
    """应用列表读出当前可信 IP 就是目标值时不重复写入。"""
    prepare_storage(storage)
    wecom_session = FakeWeComSession(trusted_ips_by_agent={"1230002": ["9.9.9.9"]})
    service = SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_session
    )

    summary = await service.sync()

    assert summary.status == "unchanged"
    assert summary.results[0].updated is False
    assert "无需覆盖" in summary.results[0].message
    assert wecom_session.calls == []
    assert wecom_session.listing_reads == 1
    assert storage.list_wecom_apps()[0].current_trusted_ips == ["9.9.9.9"]


async def test_sync_writes_and_confirms_when_listed_ip_differs(storage):
    prepare_storage(storage)
    wecom_session = FakeWeComSession(trusted_ips_by_agent={"1230002": ["1.1.1.1"]})
    service = SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_session
    )

    summary = await service.sync()

    assert summary.status == "ok"
    assert summary.results[0].updated is True
    assert "已回读确认" in summary.results[0].message
    assert "原值 1.1.1.1" in summary.results[0].message
    assert wecom_session.calls == [("1230002", "", "9.9.9.9")]
    assert wecom_session.listing_reads == 2
    stored_app = storage.list_wecom_apps()[0]
    assert stored_app.current_trusted_ips == ["9.9.9.9"]
    assert stored_app.last_synced_ip == "9.9.9.9"


async def test_sync_writes_when_listed_ip_has_extra_entries(storage):
    """后台同时存在其它可信 IP 时也要覆盖成仅最新一条。"""
    prepare_storage(storage)
    wecom_service = FakeWeComSession(trusted_ips_by_agent={"1230002": ["9.9.9.9", "1.1.1.1"]})
    service = SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_service
    )

    summary = await service.sync()

    assert summary.status == "ok"
    assert summary.results[0].updated is True
    assert wecom_service.calls == [("1230002", "", "9.9.9.9")]


async def test_sync_writes_when_listed_ip_is_empty(storage):
    prepare_storage(storage)
    wecom_service = FakeWeComSession(trusted_ips_by_agent={"1230002": []})
    service = SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_service
    )

    summary = await service.sync()

    assert summary.status == "ok"
    assert "原值 空" in summary.results[0].message
    assert wecom_service.calls == [("1230002", "", "9.9.9.9")]


async def test_sync_writes_when_app_missing_from_application_list(storage):
    """列表接口没给出这个应用时不漏写，说明里注明没读到原值。"""
    prepare_storage(storage)
    wecom_service = FakeWeComSession(trusted_ips_by_agent={})
    service = SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_service
    )

    summary = await service.sync()

    assert summary.status == "ok"
    assert "已回读确认" in summary.results[0].message
    assert "未能读到原值" in summary.results[0].message
    assert wecom_service.calls == [("1230002", "", "9.9.9.9")]


async def test_sync_marks_unverified_when_application_list_read_fails(storage):
    """应用列表读不出来时仍照写，但只标注"未完成回读校验"。"""
    prepare_storage(storage)
    wecom_service = FakeWeComSession(listing_error_message="企业微信返回 HTTP 404")
    service = SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_service
    )

    summary = await service.sync()

    assert summary.status == "ok"
    assert summary.results[0].updated is True
    assert "回读校验未完成" in summary.results[0].message
    assert storage.list_wecom_apps()[0].last_synced_ip == "9.9.9.9"


async def test_sync_fails_when_read_back_still_shows_old_ip(storage):
    """接口说写入成功、回读发现没变时必须报失败，不能假成功。"""
    prepare_storage(storage)
    wecom_service = FakeWeComSession(
        trusted_ips_by_agent={"1230002": ["1.1.1.1"]}, writes_take_effect=False
    )
    service = SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_service
    )

    summary = await service.sync()

    assert summary.status == "failed"
    assert summary.results[0].success is False
    assert summary.results[0].updated is True
    assert "回读校验不通过" in summary.results[0].message
    stored_app = storage.list_wecom_apps()[0]
    assert stored_app.last_synced_ip is None
    assert "回读校验不通过" in stored_app.last_error
    assert stored_app.current_trusted_ips == ["1.1.1.1"]


async def test_refresh_trusted_ips_reads_every_app_without_writing(storage):
    """只读核对：读完刷新本地读数，但不发任何写入请求，也不需要读取模板。"""
    prepare_storage(
        storage,
        apps=[
            WeComApp(agent_id="1230001", name="订单系统"),
            WeComApp(agent_id="1230002", name="客服系统"),
        ],
    )
    wecom_service = FakeWeComSession(
        trusted_ips_by_agent={"1230001": ["1.1.1.1"], "1230002": []}
    )
    service = SyncService(
        storage=storage, resolver=FakeResolver(ip="9.9.9.9"), wecom_session=wecom_service
    )

    summary = await service.refresh_trusted_ips()

    assert summary.total == 2
    assert summary.failed == 0
    assert wecom_service.calls == []
    assert wecom_service.listing_reads == 1
    readings = {app.agent_id: app.current_trusted_ips for app in storage.list_wecom_apps()}
    assert readings == {"1230001": ["1.1.1.1"], "1230002": []}


async def test_refresh_trusted_ips_counts_unreadable_apps(storage):
    prepare_storage(storage)
    service = SyncService(
        storage=storage, resolver=FakeResolver(), wecom_session=FakeWeComSession()
    )

    summary = await service.refresh_trusted_ips()

    assert summary.failed == 1
    assert "0/1" in summary.message
    assert "1 个读取失败" in summary.message


async def test_refresh_trusted_ips_fails_without_apps(storage):
    service = SyncService(
        storage=storage, resolver=FakeResolver(), wecom_session=FakeWeComSession()
    )

    with pytest.raises(WeComAdminError, match="应用"):
        await service.refresh_trusted_ips()
