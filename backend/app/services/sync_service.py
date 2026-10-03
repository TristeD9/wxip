"""可信 IP 同步编排：取公网 IP → 逐个应用覆盖可信 IP。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

from app.models import (
    APP_ID_PLACEHOLDER,
    IKuaiSettings,
    PublicIpObservation,
    RequestTemplate,
    SYNC_STATUS_FAILED,
    SYNC_STATUS_OK,
    SYNC_STATUS_UNCHANGED,
    SyncAppResult,
    SyncStatus,
    SyncSummary,
    WeComApp,
)
from app.services.public_ip import PublicIpError
from app.storage import AppStorage
from app.wecom.admin_browser import WeComAdminError
from app.wecom.curl_template import required_placeholders

logger = logging.getLogger(__name__)


class PublicIpResolverProtocol(Protocol):
    """同步服务只依赖这一个解析入口，便于测试注入。"""

    async def resolve(self, ikuai_settings: IKuaiSettings | None) -> PublicIpObservation: ...


class WeComSessionProtocol(Protocol):
    """同步服务只依赖登录校验与请求重放两个动作。"""

    async def ensure_logged_in(self) -> None: ...

    async def replay_request(
        self, template: RequestTemplate, *, agent_id: str, app_id: str, ip: str
    ) -> str: ...


class SyncService:
    """执行一次完整的可信 IP 覆盖流程。"""

    def __init__(
        self,
        *,
        storage: AppStorage,
        resolver: PublicIpResolverProtocol,
        wecom_session: WeComSessionProtocol,
    ) -> None:
        self._storage = storage
        self._resolver = resolver
        self._wecom_session = wecom_session

    async def sync(self, *, force: bool = False) -> SyncSummary:
        """解析最新公网 IP，并把所有自建应用的可信 IP 覆盖为它。"""
        started_at = _utc_now()
        previous = self._storage.latest_public_ip()

        try:
            observation = await self._resolver.resolve(self._storage.get_ikuai_settings())
        except PublicIpError as error:
            return self._fail(started_at, public_ip=None, message=str(error))

        self._storage.record_public_ip(observation)
        if not force and self._is_already_synced(observation, previous):
            return self._finish(
                started_at,
                public_ip=observation.ip,
                status=SYNC_STATUS_UNCHANGED,
                message="公网 IP 未变化，跳过同步",
            )

        template = self._storage.get_request_template()
        if template is None:
            return self._fail(started_at, observation.ip, "尚未录制可信 IP 请求模板")
        apps = self._storage.list_wecom_apps()
        if not apps:
            return self._fail(started_at, observation.ip, "尚未发现任何企业微信自建应用")

        try:
            await self._wecom_session.ensure_logged_in()
        except WeComAdminError as error:
            return self._fail(started_at, observation.ip, str(error))

        results = [await self._sync_one_app(app, template, observation.ip) for app in apps]
        succeeded = sum(1 for result in results if result.success)
        status = SYNC_STATUS_OK if succeeded == len(results) else SYNC_STATUS_FAILED
        message = f"已覆盖 {succeeded}/{len(results)} 个应用的可信 IP"
        return self._finish(
            started_at,
            public_ip=observation.ip,
            status=status,
            message=message,
            results=results,
        )

    async def _sync_one_app(self, app: WeComApp, template: RequestTemplate, ip: str) -> SyncAppResult:
        missing_id_message = self._check_required_app_id(app, template)
        if missing_id_message is not None:
            self._storage.update_app_sync_result(
                app.agent_id, synced_ip=None, synced_at=None, error=missing_id_message
            )
            return SyncAppResult(
                agent_id=app.agent_id, name=app.name, success=False, message=missing_id_message
            )
        try:
            await self._wecom_session.replay_request(
                template, agent_id=app.agent_id, app_id=app.console_app_id or "", ip=ip
            )
        except WeComAdminError as error:
            message = str(error)
            self._storage.update_app_sync_result(
                app.agent_id, synced_ip=None, synced_at=None, error=message
            )
            logger.warning("应用 %s 同步失败：%s", app.agent_id, message)
            return SyncAppResult(agent_id=app.agent_id, name=app.name, success=False, message=message)

        synced_at = _utc_now().isoformat()
        self._storage.update_app_sync_result(
            app.agent_id, synced_ip=ip, synced_at=synced_at, error=None
        )
        return SyncAppResult(agent_id=app.agent_id, name=app.name, success=True, message=f"已覆盖为 {ip}")

    @staticmethod
    def _check_required_app_id(app: WeComApp, template: RequestTemplate) -> str | None:
        """模板要求管理后台应用编号、但该应用没记录时，提前给出可读原因。"""
        if APP_ID_PLACEHOLDER in required_placeholders(template) and not app.console_app_id:
            return (
                f"模板需要 {APP_ID_PLACEHOLDER}（管理后台的应用编号），但应用 {app.agent_id} 没有该编号，"
                "请在「企业微信」页用「agentid,应用名,控制台应用编号」手工补录"
            )
        return None

    def _is_already_synced(
        self, observation: PublicIpObservation, previous: PublicIpObservation | None
    ) -> bool:
        if previous is None or previous.ip != observation.ip:
            return False
        apps = self._storage.list_wecom_apps()
        if not apps:
            return False
        return all(app.last_synced_ip == observation.ip and not app.last_error for app in apps)

    def _fail(self, started_at: datetime, public_ip: str | None, message: str) -> SyncSummary:
        logger.error("可信 IP 同步失败：%s", message)
        return self._finish(
            started_at, public_ip=public_ip, status=SYNC_STATUS_FAILED, message=message
        )

    def _finish(
        self,
        started_at: datetime,
        *,
        public_ip: str | None,
        status: SyncStatus,
        message: str,
        results: list[SyncAppResult] | None = None,
    ) -> SyncSummary:
        summary = SyncSummary(
            started_at=started_at,
            finished_at=_utc_now(),
            public_ip=public_ip,
            status=status,
            message=message,
            results=results or [],
        )
        self._storage.record_sync_summary(summary)
        return summary


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

