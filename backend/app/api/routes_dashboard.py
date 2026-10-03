"""仪表盘聚合接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_default_sync_settings,
    get_scheduler,
    get_storage,
    get_wecom_session,
    require_session,
)
from app.models import SyncSettings
from app.services.scheduler import SyncScheduler
from app.storage import AppStorage
from app.wecom.admin_browser import WeComAdminSession

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/state")
async def read_dashboard_state(
    storage: AppStorage = Depends(get_storage),
    wecom_session: WeComAdminSession = Depends(get_wecom_session),
    scheduler: SyncScheduler = Depends(get_scheduler),
    default_sync_settings: SyncSettings = Depends(get_default_sync_settings),
    _session: str = Depends(require_session),
) -> dict[str, object]:
    """一次性返回仪表盘需要的全部状态。"""
    events = storage.list_sync_summaries(limit=1)
    return {
        "ikuai": _describe_ikuai(storage),
        "wecom_login": wecom_session.login_state().model_dump(),
        "template_configured": storage.get_request_template() is not None,
        "apps": [app.model_dump() for app in storage.list_wecom_apps()],
        "sync_settings": storage.get_sync_settings(default_sync_settings).model_dump(),
        "latest_public_ip": _describe_latest_ip(storage),
        "last_sync": events[0].model_dump() if events else None,
        "scheduler_running": scheduler.is_running(),
    }


def _describe_ikuai(storage: AppStorage) -> dict[str, object]:
    settings = storage.get_ikuai_settings()
    if settings is None:
        return {"configured": False}
    return {
        "configured": True,
        "base_url": settings.base_url,
        "username": settings.username,
    }


def _describe_latest_ip(storage: AppStorage) -> dict[str, object] | None:
    observation = storage.latest_public_ip()
    return observation.model_dump() if observation else None

