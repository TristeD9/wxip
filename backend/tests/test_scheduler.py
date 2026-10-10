"""后台定时任务的决策：前置条件齐备且开启自动同步时才执行一轮。"""

import pytest

from app.models import IKuaiSettings, RequestTemplate, SyncSettings, WeComApp
from app.services.scheduler import SyncScheduler
from app.storage import AppStorage


class FakeSyncService:
    """只记录被调用了多少次同步，不碰网络。"""

    def __init__(self) -> None:
        self.sync_calls = 0

    async def sync(self, *, force: bool = False) -> None:
        self.sync_calls += 1


@pytest.fixture
def storage(tmp_path):
    store = AppStorage(tmp_path / "app.sqlite3")
    store.initialize()
    return store


def build_scheduler(storage: AppStorage, sync_service: FakeSyncService) -> SyncScheduler:
    return SyncScheduler(
        sync_service=sync_service, storage=storage, default_settings=SyncSettings()
    )


async def test_run_once_syncs_when_auto_enabled(storage):
    storage.save_ikuai_settings(IKuaiSettings(base_url="http://192.168.1.1"))
    storage.save_request_template(
        RequestTemplate(method="POST", url="https://example.com/save", body="{ip}")
    )
    storage.replace_wecom_apps([WeComApp(agent_id="1230002", name="客服系统")])
    storage.save_sync_settings(SyncSettings(auto_enabled=True, interval_seconds=60))
    sync_service = FakeSyncService()

    await build_scheduler(storage, sync_service).run_once()

    assert sync_service.sync_calls == 1


async def test_run_once_skips_when_auto_disabled(storage):
    storage.save_ikuai_settings(IKuaiSettings(base_url="http://192.168.1.1"))
    storage.save_request_template(
        RequestTemplate(method="POST", url="https://example.com/save", body="{ip}")
    )
    storage.replace_wecom_apps([WeComApp(agent_id="1230002", name="客服系统")])
    storage.save_sync_settings(SyncSettings(auto_enabled=False, interval_seconds=60))
    sync_service = FakeSyncService()

    await build_scheduler(storage, sync_service).run_once()

    assert sync_service.sync_calls == 0


async def test_run_once_skips_without_prerequisites(storage):
    storage.save_sync_settings(SyncSettings(auto_enabled=True, interval_seconds=60))
    sync_service = FakeSyncService()

    await build_scheduler(storage, sync_service).run_once()

    assert sync_service.sync_calls == 0
