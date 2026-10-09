"""同步设置、手动触发与历史记录接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_storage, get_sync_service, require_session
from app.models import SyncSettings, SyncSummary
from app.services.scheduler import MIN_INTERVAL_SECONDS
from app.services.sync_service import SyncService
from app.storage import AppStorage

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncSettingsPayload(BaseModel):
    """前端提交的自动同步设置。"""

    auto_enabled: bool = True
    interval_seconds: int = Field(default=300, ge=MIN_INTERVAL_SECONDS, le=86_400)


class SyncRunPayload(BaseModel):
    """手动触发同步的参数。"""

    force: bool = False


@router.get("/settings", response_model=SyncSettings)
async def read_sync_settings(
    storage: AppStorage = Depends(get_storage), _session: str = Depends(require_session)
) -> SyncSettings:
    """返回自动同步设置。"""
    return storage.get_sync_settings(SyncSettings())


@router.put("/settings", response_model=SyncSettings)
async def save_sync_settings(
    payload: SyncSettingsPayload,
    storage: AppStorage = Depends(get_storage),
    _session: str = Depends(require_session),
) -> SyncSettings:
    """保存自动同步设置。"""
    settings = SyncSettings.model_validate(payload.model_dump())
    storage.save_sync_settings(settings)
    return settings


@router.post("/run", response_model=SyncSummary)
async def run_sync(
    payload: SyncRunPayload,
    sync_service: SyncService = Depends(get_sync_service),
    _session: str = Depends(require_session),
) -> SyncSummary:
    """立即执行一次同步；``force`` 为真时忽略 IP 未变化检查，重新写入全部应用。"""
    return await sync_service.sync(force=payload.force)


@router.get("/events", response_model=list[SyncSummary])
async def list_sync_events(
    limit: int = 50,
    storage: AppStorage = Depends(get_storage),
    _session: str = Depends(require_session),
) -> list[SyncSummary]:
    """返回最近的同步历史。"""
    return storage.list_sync_summaries(limit=max(1, min(limit, 200)))

