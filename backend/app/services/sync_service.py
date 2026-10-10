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
    TrustedIpCheckSummary,
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
    """同步服务只依赖登录校验、读取当前可信 IP 与请求重放三类动作。"""

    async def ensure_logged_in(self) -> None: ...

    async def read_app_trusted_ips(self) -> dict[str, list[str]]: ...

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
        """核对所有自建应用的当前可信 IP，只覆盖不一致的，并回读确认。

        ``force`` 为真时忽略读到的当前值，直接重写一遍（真正的强制覆盖）。
        """
        started_at = _utc_now()

        try:
            observation = await self._resolver.resolve(self._storage.get_ikuai_settings())
        except PublicIpError as error:
            return self._fail(started_at, public_ip=None, message=str(error))

        self._storage.record_public_ip(observation)
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

        current_ips_by_agent = await self._read_app_trusted_ips(apps)
        results = [
            await self._sync_one_app(
                app, template, current_ips_by_agent.get(app.agent_id), observation.ip, force
            )
            for app in apps
        ]
        if any(result.updated for result in results):
            results = await self._verify_written_apps(
                apps, results, current_ips_by_agent, observation.ip
            )
        return self._summarize(started_at, public_ip=observation.ip, results=results)

    async def refresh_trusted_ips(self) -> TrustedIpCheckSummary:
        """只读核对所有应用的当前可信 IP，不修改企业微信里的任何配置。

        Raises:
            WeComAdminError: 没有应用清单，或企业微信登录态失效。
        """
        apps = self._storage.list_wecom_apps()
        if not apps:
            raise WeComAdminError("尚未发现任何企业微信自建应用")
        await self._wecom_session.ensure_logged_in()

        collected = await self._read_app_trusted_ips(apps)
        failed = len(apps) - len(collected)
        suffix = f"，{failed} 个读取失败" if failed else ""
        return TrustedIpCheckSummary(
            checked_at=_utc_now(),
            total=len(apps),
            failed=failed,
            message=f"已读取 {len(collected)}/{len(apps)} 个应用的当前可信 IP{suffix}",
        )

    async def _read_app_trusted_ips(self, apps: list[WeComApp]) -> dict[str, list[str]]:
        """打开应用管理页，读出每个应用当前的可信 IP。

        返回 ``{agent_id: [当前可信 IP]}``；读不到的应用不出现在字典里。
        """
        try:
            listed = await self._wecom_session.read_app_trusted_ips()
        except WeComAdminError as error:
            logger.warning("从应用列表读取当前可信 IP 失败：%s", error)
            return {}
        collected: dict[str, list[str]] = {}
        checked_at = _utc_now().isoformat()
        for app in apps:
            if app.agent_id not in listed:
                continue
            self._storage.record_app_trusted_ips(
                app.agent_id, ips=listed[app.agent_id], checked_at=checked_at
            )
            collected[app.agent_id] = listed[app.agent_id]
        return collected

    async def _sync_one_app(
        self,
        app: WeComApp,
        template: RequestTemplate,
        current_ips: list[str] | None,
        ip: str,
        force: bool,
    ) -> SyncAppResult:
        """按已读到的当前值决定跳过还是写入，返回写入阶段的结果。"""
        missing_id_message = self._check_required_app_id(app, template)
        if missing_id_message is not None:
            self._storage.update_app_sync_result(
                app.agent_id, synced_ip=None, synced_at=None, error=missing_id_message
            )
            return SyncAppResult(
                agent_id=app.agent_id, name=app.name, success=False, message=missing_id_message
            )

        if not force and current_ips == [ip]:
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

        return SyncAppResult(
            agent_id=app.agent_id,
            name=app.name,
            success=True,
            message=f"已覆盖为 {ip}{_describe_previous_ips(current_ips)}",
            updated=True,
        )

    async def _verify_written_apps(
        self,
        apps: list[WeComApp],
        results: list[SyncAppResult],
        previous_ips_by_agent: dict[str, list[str]],
        ip: str,
    ) -> list[SyncAppResult]:
        """写过之后再统一读一次，确认这些应用现在真的是目标 IP。"""
        confirmed = await self._read_app_trusted_ips(apps)
        verified_results: list[SyncAppResult] = []
        for app, result in zip(apps, results):
            if not result.updated or not result.success:
                verified_results.append(result)
                continue
            verified_results.append(
                self._finish_written_app(
                    app, confirmed.get(app.agent_id), previous_ips_by_agent.get(app.agent_id), ip
                )
            )
        return verified_results

    def _finish_written_app(
        self,
        app: WeComApp,
        verified_ips: list[str] | None,
        previous_ips: list[str] | None,
        ip: str,
    ) -> SyncAppResult:
        """按回读结果给写过的应用定性：确认成功、校验未完成、还是校验不通过。"""
        if verified_ips is not None and verified_ips != [ip]:
            message = (
                f"写入已提交，但回读校验不通过：当前可信 IP 为 "
                f"{'、'.join(verified_ips) or '空'}，目标为 {ip}"
            )
            self._storage.update_app_sync_result(
                app.agent_id, synced_ip=None, synced_at=None, error=message
            )
            logger.warning("应用 %s 回读校验失败：%s", app.agent_id, message)
            return SyncAppResult(
                agent_id=app.agent_id,
                name=app.name,
                success=False,
                message=message,
                updated=True,
            )

        synced_at = _utc_now().isoformat()
        self._storage.update_app_sync_result(
            app.agent_id, synced_ip=ip, synced_at=synced_at, error=None
        )
        verification_note = "（已回读确认）"
        if verified_ips is None:
            # 读不到就不敢说确认过，只按写入结果记录已覆盖
            verification_note = "（回读校验未完成）"
            self._storage.record_app_trusted_ips(app.agent_id, ips=[ip], checked_at=synced_at)
        return SyncAppResult(
            agent_id=app.agent_id,
            name=app.name,
            success=True,
            message=f"已覆盖为 {ip}{verification_note}{_describe_previous_ips(previous_ips)}",
            updated=True,
        )

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


def _describe_previous_ips(current_ips: list[str] | None) -> str:
    """拼出"覆盖前是什么"的补充说明；读不到原值时如实说明。"""
    if current_ips is None:
        return "（未能读到原值）"
    return f"（原值 {'、'.join(current_ips) or '空'}）"
