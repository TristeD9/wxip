"""后台定时任务的决策：开着自动同步就核对并写入，关掉只做只读核对。"""

import pytest

from app.models import IKuaiSettings, RequestTemplate, SyncSettings, WeComApp
from app.services.scheduler import SyncScheduler
from app.storage import AppStorage


class FakeSyncService:
    """只记录被调用了哪个动作，不碰网络。"""

    def __init__(self) -> None:
        self.sync_calls = 0
        self.refresh_calls = 0

    async def sync(self, *, force: bool = False) -> None:
        self.sync_calls += 1

    async def refresh_trusted_ips(self) -> None:
        self.refresh_calls += 1


@pytest.fixture
def storage(tmp_path):
    store = AppStorage(tmp_path / "app.sqlite3")
    store.initialize()
    return store


def prepare_ready_storage(storage: AppStorage) -> None:
    storage.save_ikuai_settings(IKuaiSettings(base_url="http://192.168.1.1"))
    storage.save_request_template(
        RequestTemplate(method="POST", url="https://example.com/save", body="{ip}")
    )
    storage.replace_wecom_apps([WeComApp(agent_id="1230002", name="客服系统")])


def build_scheduler(storage: AppStorage, sync_service: FakeSyncService) -> SyncScheduler:
    return SyncScheduler(
        sync_service=sync_service, storage=storage, default_settings=SyncSettings()
    )


async def test_run_once_syncs_when_auto_enabled(storage):
    prepare_ready_storage(storage)
    storage.save_sync_settings(SyncSettings(auto_enabled=True, interval_seconds=60))
    sync_service = FakeSyncService()

    await build_scheduler(storage, sync_service).run_once()

    assert (sync_service.sync_calls, sync_service.refresh_calls) == (1, 0)


async def test_run_once_only_refreshes_when_auto_disabled(storage):
    """自动写入关闭后仍要定时读取，否则面板上的当前可信 IP 会一直停在旧值。"""
    prepare_ready_storage(storage)
    storage.save_sync_settings(SyncSettings(auto_enabled=False, interval_seconds=60))
    sync_service = FakeSyncService()

    await build_scheduler(storage, sync_service).run_once()

    assert (sync_service.sync_calls, sync_service.refresh_calls) == (0, 1)


async def test_run_once_refreshes_when_sync_is_not_ready(storage):
    """没配 iKuai 与写入模板时写不了，但只要有应用清单就仍然只读核对。"""
    storage.replace_wecom_apps([WeComApp(agent_id="1230002", name="客服系统")])
    storage.save_sync_settings(SyncSettings(auto_enabled=True, interval_seconds=60))
    sync_service = FakeSyncService()

    await build_scheduler(storage, sync_service).run_once()

    assert (sync_service.sync_calls, sync_service.refresh_calls) == (0, 1)


async def test_run_once_skips_without_apps(storage):
    storage.save_sync_settings(SyncSettings(auto_enabled=False, interval_seconds=60))
    sync_service = FakeSyncService()

    await build_scheduler(storage, sync_service).run_once()

    assert (sync_service.sync_calls, sync_service.refresh_calls) == (0, 0)
