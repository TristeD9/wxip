"""后台定时同步：按配置间隔触发一次可信 IP 检查。"""

from __future__ import annotations

import asyncio
import logging

from app.models import SyncSettings
from app.services.sync_service import SyncService
from app.storage import AppStorage

logger = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 30


class SyncScheduler:
    """用单个 asyncio 任务串行执行同步，避免并发改动企业微信配置。"""

    def __init__(
        self, *, sync_service: SyncService, storage: AppStorage, default_settings: SyncSettings
    ) -> None:
        self._sync_service = sync_service
        self._storage = storage
        self._default_settings = default_settings
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """启动后台任务，重复调用不会产生第二个循环。"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        """停止后台任务。"""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def is_running(self) -> bool:
        """返回后台任务是否存活。"""
        return self._task is not None and not self._task.done()

    async def _run_forever(self) -> None:
        while True:
            settings = self._storage.get_sync_settings(self._default_settings)
            if settings.auto_enabled and self._is_ready():
                try:
                    await self._sync_service.sync()
                except Exception:  # 后台循环必须存活，异常记录后继续下一轮
                    logger.exception("定时同步出现未预期异常")
            else:
                logger.debug("自动同步前置条件未就绪，跳过本轮")
            await asyncio.sleep(max(settings.interval_seconds, MIN_INTERVAL_SECONDS))

    def _is_ready(self) -> bool:
        """前置条件缺失时不产生失败历史，只在需要的时候提示。"""
        return (
            self._storage.get_ikuai_settings() is not None
            and self._storage.get_request_template() is not None
            and bool(self._storage.list_wecom_apps())
        )
