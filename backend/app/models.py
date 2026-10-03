"""跨模块共享的数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

IP_PLACEHOLDER = "{ip}"
AGENT_ID_PLACEHOLDER = "{agent_id}"
APP_ID_PLACEHOLDER = "{app_id}"

SYNC_STATUS_OK = "ok"
SYNC_STATUS_UNCHANGED = "unchanged"
SYNC_STATUS_FAILED = "failed"

SyncStatus = Literal["ok", "unchanged", "failed"]


class IKuaiSettings(BaseModel):
    """iKuai Web 管理端的连接参数。"""

    base_url: str
    username: str = "admin"
    password: str = ""
    verify_tls: bool = True
    timeout_seconds: float = 10.0


class PublicIpObservation(BaseModel):
    """一次公网 IP 观测结果。"""

    ip: str
    source: str
    checked_at: datetime


class WeComApp(BaseModel):
    """一个企业微信自建应用的同步状态。"""

    agent_id: str
    name: str
    console_app_id: str | None = None
    last_synced_ip: str | None = None
    last_synced_at: datetime | None = None
    last_error: str | None = None


class RenderedRequest(BaseModel):
    """把模板中的占位符替换后，可直接发送的请求。"""

    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None


class RequestTemplate(BaseModel):
    """从浏览器 cURL 录制中提取的请求模板。"""

    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None

    def render(self, *, agent_id: str, app_id: str, ip: str) -> RenderedRequest:
        """用目标应用的标识与最新公网 IP 渲染请求。

        ``agent_id`` 替换 ``{agent_id}``，``app_id`` 替换 ``{app_id}``（管理后台
        自己那套 16 位应用编号），``ip`` 替换 ``{ip}``。
        """

        def substitute(text: str) -> str:
            return (
                text.replace(AGENT_ID_PLACEHOLDER, agent_id)
                .replace(APP_ID_PLACEHOLDER, app_id)
                .replace(IP_PLACEHOLDER, ip)
            )

        return RenderedRequest(
            method=self.method,
            url=substitute(self.url),
            headers={key: substitute(value) for key, value in self.headers.items()},
            body=None if self.body is None else substitute(self.body),
        )


class SyncAppResult(BaseModel):
    """单个应用的同步结果。"""

    agent_id: str
    name: str
    success: bool
    message: str


class SyncSummary(BaseModel):
    """一次同步的完整结果。"""

    started_at: datetime
    finished_at: datetime
    public_ip: str | None = None
    status: SyncStatus = SYNC_STATUS_FAILED
    message: str = ""
    results: list[SyncAppResult] = Field(default_factory=list)


class SyncSettings(BaseModel):
    """自动同步开关与间隔。"""

    auto_enabled: bool = True
    interval_seconds: int = 300


class IpProviderProbe(BaseModel):
    """iKuai 探测请求的原始返回，用于前端排障。"""

    request_name: str
    ok: bool
    payload: object | None = None
    error: str | None = None


class WeComLoginState(BaseModel):
    """企业微信管理后台的扫码登录状态。"""

    status: Literal["idle", "waiting_scan", "logged_in", "failed"] = "idle"
    qr_png_base64: str | None = None
    message: str = ""
    updated_at: datetime


class AdminAccount(BaseModel):
    """面板本地管理员账号。"""

    username: str
    password_hash: str
    created_at: datetime
    updated_at: datetime

