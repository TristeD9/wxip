"""公网 IP 解析：优先 iKuai，失败时回退到外部回显服务。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.ikuai.client import IKuaiClient, IKuaiError
from app.ikuai.parser import is_public_ip
from app.models import IKuaiSettings, PublicIpObservation

logger = logging.getLogger(__name__)

ECHO_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("api.ipify.org", "https://api.ipify.org"),
    ("ipv4.icanhazip.com", "https://ipv4.icanhazip.com"),
    ("ifconfig.me", "https://ifconfig.me/ip"),
)


class PublicIpError(RuntimeError):
    """所有公网 IP 来源都失败。"""


class PublicIpResolver:
    """按 iKuai → 外部回显服务的顺序解析公网 IP。"""

    def __init__(
        self,
        *,
        echo_providers: tuple[tuple[str, str], ...] = ECHO_PROVIDERS,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._echo_providers = echo_providers
        self._timeout_seconds = timeout_seconds

    async def resolve(self, ikuai_settings: IKuaiSettings | None) -> PublicIpObservation:
        """返回一次公网 IP 观测结果。

        iKuai 不可用时记录警告并回退到外部服务，全部失败才抛异常。

        Raises:
            PublicIpError: 所有来源都拿不到合法公网 IP。
        """
        failure_messages: list[str] = []

        if ikuai_settings is not None:
            try:
                address = await self._resolve_from_ikuai(ikuai_settings)
                return self._observe(address, source="ikuai")
            except (IKuaiError, ValueError, httpx.HTTPError) as error:
                message = f"iKuai 获取公网 IP 失败，改用外部回显服务：{error}"
                logger.warning(message)
                failure_messages.append(message)
        else:
            failure_messages.append("尚未配置 iKuai 连接参数")

        for provider_name, provider_url in self._echo_providers:
            try:
                address = await self._resolve_from_echo(provider_url)
                return self._observe(address, source=provider_name)
            except (httpx.HTTPError, ValueError) as error:
                failure_messages.append(f"{provider_name} 获取失败：{error}")

        raise PublicIpError("；".join(failure_messages))

    async def _resolve_from_ikuai(self, settings: IKuaiSettings) -> str:
        async with IKuaiClient(settings) as client:
            return await client.get_public_ip()

    async def _resolve_from_echo(self, provider_url: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(provider_url)
            response.raise_for_status()
        address = response.text.strip()
        if not is_public_ip(address):
            raise ValueError(f"回显服务返回了非法地址：{address!r}")
        return address

    @staticmethod
    def _observe(address: str, *, source: str) -> PublicIpObservation:
        return PublicIpObservation(ip=address, source=source, checked_at=datetime.now(timezone.utc))

