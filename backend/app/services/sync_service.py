"""可信 IP 同步编排：取公网 IP → 读取各应用当前可信 IP → 只覆盖不一致的应用。"""

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
    """同步服务只依赖登录校验、读取当前可信 IP 与请求重放三个动作。"""

    async def ensure_logged_in(self) -> None: ...

    async def read_trusted_ips(
        self, template: RequestTemplate, *, agent_id: str, app_id: str, ip: str
    ) -> list[str] | None: ...

    async def replay_request(
        self, template: RequestTemplate, *, agent_id: str, app_id: str, ip: str
    ) -> str: ...


class SyncService:
    """核对各应用当前可信 IP，并按需覆盖成本次解析出的公网 IP。"""

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
        """核对所有自建应用的当前可信 IP，只把与最新公网 IP 不一致的覆盖掉。"""
        started_at = _utc_now()
        previous = self._storage.latest_public_ip()

        try:
            observation = await self._resolver.resolve(self._storage.get_ikuai_settings())
        except PublicIpError as error:
            return self._fail(started_at, public_ip=None, message=str(error))

        self._storage.record_public_ip(observation)
        read_template = self._storage.get_read_template()
        # 录了读取模板就逐个应用比对真实状态，此时本地记录不再作为跳过依据
        if read_template is None and not force and self._is_already_synced(observation, previous):
            return self._finish(
                started_at,
                public_ip=observation.ip,
                status=SYNC_STATUS_UNCHANGED,
                message="公网 IP 未变化，自动同步已跳过；需要重新写入请在面板点「立即同步」",
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

        results = [
            await self._sync_one_app(app, template, read_template, observation.ip) for app in apps
        ]
        return self._summarize(started_at, public_ip=observation.ip, results=results)

    async def _sync_one_app(
        self,
        app: WeComApp,
        template: RequestTemplate,
        read_template: RequestTemplate | None,
        ip: str,
    ) -> SyncAppResult:
        missing_id_message = self._check_required_app_id(app, template)
        if missing_id_message is not None:
            self._storage.update_app_sync_result(
                app.agent_id, synced_ip=None, synced_at=None, error=missing_id_message
            )
            return SyncAppResult(
                agent_id=app.agent_id, name=app.name, success=False, message=missing_id_message
            )

        current_ips: list[str] | None = None
        read_error: str | None = None
        if read_template is not None:
            current_ips, read_error = await self._read_current_trusted_ips(app, read_template, ip)

        if current_ips == [ip]:
            self._storage.record_app_trusted_ips(
                app.agent_id, ips=current_ips, checked_at=_utc_now().isoformat()
            )
            return SyncAppResult(
                agent_id=app.agent_id,
                name=app.name,
                success=True,
                message=f"当前可信 IP 已是 {ip}，无需覆盖",
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
        # 写入成功后后台的可信 IP 就是这个值，直接记为已知状态，省掉一次读取
        self._storage.record_app_trusted_ips(app.agent_id, ips=[ip], checked_at=synced_at)
        return SyncAppResult(
            agent_id=app.agent_id,
            name=app.name,
            success=True,
            message=f"已覆盖为 {ip}{_describe_previous_ips(current_ips, read_error)}",
            updated=True,
        )

    async def _read_current_trusted_ips(
        self, app: WeComApp, read_template: RequestTemplate, ip: str
    ) -> tuple[list[str] | None, str | None]:
        """读取应用当前可信 IP，返回 (IP 列表, 错误说明)，两者最多一个非空。"""
        blocker = self._check_required_app_id(app, read_template)
        if blocker is not None:
            return None, blocker
        try:
            trusted_ips = await self._wecom_session.read_trusted_ips(
                read_template, agent_id=app.agent_id, app_id=app.console_app_id or "", ip=ip
            )
        except WeComAdminError as error:
            logger.warning("应用 %s 读取当前可信 IP 失败：%s", app.agent_id, error)
            return None, str(error)
        if trusted_ips is None:
            return None, "响应里没有可识别的可信 IP 列表"
        self._storage.record_app_trusted_ips(
            app.agent_id, ips=trusted_ips, checked_at=_utc_now().isoformat()
        )
        return trusted_ips, None

    def _summarize(
        self, started_at: datetime, *, public_ip: str, results: list[SyncAppResult]
    ) -> SyncSummary:
        """按每个应用的写没写、成没成，给整次同步定状态与文案。"""
        updated = [result for result in results if result.updated]
        failed = [result for result in results if not result.success]
        if failed:
            status = SYNC_STATUS_FAILED
            message = f"核对 {len(results)} 个应用：更新 {len(updated)} 个，{len(failed)} 个失败"
        elif updated:
            status = SYNC_STATUS_OK
            message = f"核对 {len(results)} 个应用：已更新 {len(updated)} 个的可信 IP"
        else:
            status = SYNC_STATUS_UNCHANGED
            message = f"核对 {len(results)} 个应用：当前可信 IP 均已是 {public_ip}"
        return self._finish(
            started_at,
            public_ip=public_ip,
            status=status,
            message=message,
            results=results,
        )

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


def _describe_previous_ips(current_ips: list[str] | None, read_error: str | None) -> str:
    """拼出"覆盖前是什么"的补充说明；读不到原值时说明原因。"""
    if current_ips is not None:
        return f"（原值 {'、'.join(current_ips) or '空'}）"
    if read_error is not None:
        return f"（未能读到原值：{read_error[:120]}）"
    return ""

