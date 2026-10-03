"""FastAPI 应用装配与生命周期管理。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import routes_auth, routes_dashboard, routes_ikuai, routes_sync, routes_wecom
from app.config import Settings
from app.login_throttle import LoginThrottle
from app.models import SyncSettings
from app.services.public_ip import PublicIpResolver
from app.services.scheduler import SyncScheduler
from app.services.sync_service import SyncService
from app.storage import AppStorage
from app.wecom.admin_browser import WeComAdminSession

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建应用实例，便于测试注入临时目录与配置。"""
    app_settings = settings or Settings()
    _configure_logging(app_settings.log_level)
    app_settings.ensure_directories()

    storage = AppStorage(app_settings.database_path)
    storage.initialize()

    wecom_session = WeComAdminSession(
        state_path=app_settings.wecom_state_path,
        headless=app_settings.browser_headless,
        channel=app_settings.browser_channel,
        timeout_ms=app_settings.browser_timeout_ms,
        apps_url_provider=storage.get_wecom_apps_url,
    )
    sync_service = SyncService(
        storage=storage,
        resolver=PublicIpResolver(timeout_seconds=app_settings.http_timeout_seconds),
        wecom_session=wecom_session,
    )
    default_sync_settings = SyncSettings(
        auto_enabled=app_settings.auto_sync_enabled,
        interval_seconds=app_settings.sync_interval_seconds,
    )
    scheduler = SyncScheduler(
        sync_service=sync_service, storage=storage, default_settings=default_sync_settings
    )
    login_throttle = LoginThrottle()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        scheduler.start()
        logger.info(
            "服务已启动：自动同步=%s，间隔=%s 秒",
            default_sync_settings.auto_enabled,
            default_sync_settings.interval_seconds,
        )
        try:
            yield
        finally:
            await scheduler.stop()
            await wecom_session.close()

    app = FastAPI(title="企业微信可信 IP 自动维护", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.storage = storage
    app.state.wecom_session = wecom_session
    app.state.sync_service = sync_service
    app.state.scheduler = scheduler
    app.state.default_sync_settings = default_sync_settings
    app.state.login_throttle = login_throttle

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        routes_auth.router,
        routes_dashboard.router,
        routes_ikuai.router,
        routes_wecom.router,
        routes_sync.router,
    ):
        app.include_router(router)

    @app.get("/api/health")
    async def read_health() -> dict[str, str]:
        """进程存活探针，供 Docker 与宝塔监控使用。"""
        return {"status": "ok"}

    if app_settings.frontend_dir.exists():
        app.mount(
            "/", StaticFiles(directory=str(app_settings.frontend_dir), html=True), name="frontend"
        )
    else:
        logger.warning("未找到前端目录 %s，仅提供 API", app_settings.frontend_dir)

    return app


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


app = create_app()
