"""iKuai Web 接口客户端：登录并读取 WAN 公网 IP。"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from typing import Any

import httpx

from app.ikuai.parser import extract_public_ip, extract_session_key
from app.models import IKuaiSettings, IpProviderProbe

LOGIN_PATH = "/Action/login"
CALL_PATH = "/Action/call"

_WAN_PROBE_REQUESTS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "wan(TYPE=total,data)",
        {"func_name": "wan", "action": "show", "param": {"TYPE": "total,data"}},
    ),
    (
        "wan_status(TYPE=total,data)",
        {"func_name": "wan_status", "action": "show", "param": {"TYPE": "total,data"}},
    ),
    (
        "wan_status(TYPE=data,total)",
        {"func_name": "wan_status", "action": "show", "param": {"TYPE": "data,total"}},
    ),
    ("wan_status(default)", {"func_name": "wan_status", "action": "show"}),
    (
        "homepage(TYPE=total,data)",
        {"func_name": "homepage", "action": "show", "param": {"TYPE": "total,data"}},
    ),
)

_SUCCESS_RESULT_CODES = (0, 10000, "0", "10000")
_LOGIN_HEADERS = {"X-Requested-With": "XMLHttpRequest"}

_SENSITIVE_KEYS = {
    "pass",
    "passwd",
    "password",
    "pincode",
    "lte_pincode",
    "psk",
    "wifi_psk",
    "secret",
    "token",
    "sess_key",
    "username",
    "user",
}
_SENSITIVE_KEY_SUFFIXES = ("_passwd", "_password", "_pass", "_pincode", "_psk", "_secret", "_token")
_REDACTED_VALUE = "***"


class IKuaiError(RuntimeError):
    """iKuai 连接或响应异常。"""


def normalize_base_url(raw_url: str) -> str:
    """把用户输入的地址规范成带协议、无尾斜杠的基地址。"""
    candidate = raw_url.strip().rstrip("/")
    if not candidate:
        raise ValueError("iKuai 地址不能为空")
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    return candidate


def build_login_json_payload(username: str, password: str) -> dict[str, Any]:
    """构造 JSON 登录报文，新版（含 iKuai OS 4.x 与部分 3.x）要求这种格式。"""
    return {
        "username": username,
        "passwd": _password_md5(password),
        "pass": _password_base64(password),
        "remember_password": 0,
    }


def build_login_form_payload(username: str, password: str) -> dict[str, str]:
    """构造表单登录报文，兼容只接受 form-urlencoded 的老固件。"""
    return {
        "username": username,
        "passwd": _password_md5(password),
        "pass": _password_base64(password),
        "remember_password": "",
    }


_LOGIN_PAYLOAD_BUILDERS: tuple[tuple[str, Callable[[str, str], dict[str, Any]]], ...] = (
    ("json", build_login_json_payload),
    ("form", build_login_form_payload),
)


def _password_md5(password: str) -> str:
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def _password_base64(password: str) -> str:
    return base64.b64encode(_password_md5(password).encode("utf-8")).decode("ascii")


class IKuaiClient:
    """以异步上下文管理器使用，退出时自动关闭连接。"""

    def __init__(self, settings: IKuaiSettings) -> None:
        self._settings = settings
        self._base_url = normalize_base_url(settings.base_url)
        self._session_key: str | None = None
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            verify=settings.verify_tls,
            timeout=settings.timeout_seconds,
            follow_redirects=True,
        )

    async def __aenter__(self) -> IKuaiClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """关闭底层 HTTP 连接。"""
        await self._client.aclose()

    async def login(self) -> None:
        """登录 iKuai 并保存会话 key。

        先按 JSON 报文登录，设备不接受时回退到 form-urlencoded。

        Raises:
            IKuaiError: 网络失败、响应非 JSON 或所有报文格式都被拒绝。
        """
        failures: list[str] = []
        for style, build_payload in _LOGIN_PAYLOAD_BUILDERS:
            try:
                payload = await self._post_login(style, build_payload)
            except httpx.HTTPError as error:
                raise IKuaiError(f"iKuai 登录请求失败：{error}") from error
            except IKuaiError as error:
                failures.append(f"{style}: {error}")
                continue

            if payload.get("Result") in _SUCCESS_RESULT_CODES:
                # 部分固件把 sess_key 放在响应体里，另一些只通过 Set-Cookie 下发
                session_key = extract_session_key(payload) or self._client.cookies.get("sess_key")
                if not session_key:
                    raise IKuaiError("iKuai 登录成功但响应体与 Cookie 中都没有 sess_key，请反馈该响应")
                self._session_key = session_key
                self._client.cookies.set("sess_key", session_key)
                return

            message = payload.get("ErrMsg") or payload.get("Message") or "未知错误"
            failures.append(f"{style}: {message}")

        raise IKuaiError("iKuai 登录被拒绝：" + "；".join(failures))

    async def _post_login(
        self, style: str, build_payload: Callable[[str, str], dict[str, Any]]
    ) -> dict[str, Any]:
        """按指定报文风格提交一次登录请求。"""
        payload = build_payload(self._settings.username, self._settings.password)
        headers = {**_LOGIN_HEADERS, "Referer": f"{self._base_url}/"}
        try:
            if style == "json":
                response = await self._client.post(LOGIN_PATH, json=payload, headers=headers)
            else:
                response = await self._client.post(LOGIN_PATH, data=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise IKuaiError(f"iKuai 登录请求失败：{error}") from error
        return _decode_payload(response)

    async def probe(self) -> list[IpProviderProbe]:
        """依次尝试所有 WAN 查询请求，返回脱敏后的原始响应用于排障。"""
        await self._ensure_logged_in()
        return [
            await self._try_wan_request(request_name, body)
            for request_name, body in _WAN_PROBE_REQUESTS
        ]

    async def get_public_ip(self) -> str:
        """返回 iKuai 上的 WAN 公网 IP。

        Raises:
            IKuaiError: 所有查询方式都没能解析出公网 IP。
        """
        await self._ensure_logged_in()
        for request_name, body in _WAN_PROBE_REQUESTS:
            probe = await self._try_wan_request(request_name, body)
            if not probe.ok or probe.payload is None:
                continue
            address = extract_public_ip(probe.payload)
            if address:
                return address
        raise IKuaiError("已在 iKuai 登录成功，但未从 WAN 状态中解析出公网 IP，请使用探测功能排查")

    async def _ensure_logged_in(self) -> None:
        if not self._session_key:
            await self.login()

    async def _try_wan_request(self, request_name: str, body: dict[str, Any]) -> IpProviderProbe:
        """执行一次 WAN 查询，失败也不中断，交给下一个候选请求。"""
        try:
            payload = await self._post_call(body)
        except (httpx.HTTPError, IKuaiError) as error:
            return IpProviderProbe(request_name=request_name, ok=False, error=str(error))
        return IpProviderProbe(
            request_name=request_name, ok=True, payload=redact_sensitive_values(payload)
        )

    async def _post_call(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "sess_key": self._session_key or "",
            "Referer": f"{self._base_url}/",
            **_LOGIN_HEADERS,
        }
        response = await self._client.post(CALL_PATH, json=body, headers=headers)
        response.raise_for_status()
        return _decode_payload(response)


def redact_sensitive_values(payload: object) -> object:
    """递归替换凭据字段，避免排障响应把密码、PPPoE 账号带到前端。"""
    if isinstance(payload, dict):
        return {
            key: _REDACTED_VALUE
            if _is_sensitive_key(key)
            else redact_sensitive_values(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact_sensitive_values(item) for item in payload]
    return payload


def _is_sensitive_key(key: object) -> bool:
    lowered = str(key).lower()
    return lowered in _SENSITIVE_KEYS or lowered.endswith(_SENSITIVE_KEY_SUFFIXES)


def _decode_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        snippet = response.text[:200].replace("\n", " ")
        raise IKuaiError(f"iKuai 返回的不是 JSON（可能是登录页重定向）：{snippet}") from error
    if not isinstance(payload, dict):
        raise IKuaiError("iKuai 返回的 JSON 结构不是对象")
    return payload
