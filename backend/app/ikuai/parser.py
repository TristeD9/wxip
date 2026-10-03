"""从 iKuai 的 JSON 响应中提取 WAN 公网 IP。"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterator

_IP_KEYS = (
    "wan_ip",
    "public_ip",
    "pppoe_ip",
    "ip_addr",
    "ipaddr",
    "ipv4_addr",
    "ipv4",
    "ipv6_addr",
    "ipv6",
    "ip",
)
_SESSION_KEYS = ("sess_key", "session_key", "sessionid", "session_id", "sid")
_STATUS_KEYS = ("status", "state", "link_status", "wan_status", "connect_status", "dial_status")
_ONLINE_MARKERS = {"1", "true", "yes", "online", "connected", "up", "success", "已连接", "正常"}

_PRIORITY_ONLINE_IPV4 = 0
_PRIORITY_UNKNOWN_IPV4 = 1
_PRIORITY_ONLINE_IPV6 = 2
_PRIORITY_UNKNOWN_IPV6 = 3


def extract_session_key(payload: object) -> str | None:
    """从登录响应中取出会话 key。"""
    for entry in _iter_dicts(payload):
        for key in _SESSION_KEYS:
            value = entry.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def extract_public_ip(payload: object) -> str | None:
    """从 WAN 状态响应中挑出最可能的公网 IP。

    优先在线且为 IPv4 的地址；私有地址、运营商共享地址段与回环地址都会被跳过。
    """
    candidates: list[tuple[int, str]] = []
    for entry in _iter_dicts(payload):
        for key, raw_value in entry.items():
            if not _is_ip_like_key(key):
                continue
            if not isinstance(raw_value, str):
                continue
            address = _normalize_address(raw_value)
            if address is None or not is_public_ip(address):
                continue
            candidates.append((_priority(entry, address), address))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _is_ip_like_key(key: object) -> bool:
    """识别 ip / ip_addr / pppoe_ip_addr / dhcp_ip 这类地址字段。"""
    lowered = str(key).lower()
    if lowered in _IP_KEYS:
        return True
    if "ip" not in lowered:
        return False
    return lowered.endswith(("ip", "_ip_addr", "_ipaddr", "addr"))


def is_public_ip(address: str) -> bool:
    """判断地址是否为可公网路由的单播地址。"""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv4Address):
        return parsed.is_global and not parsed.is_multicast
    return parsed.is_global and not parsed.is_multicast and not parsed.is_link_local


def _priority(entry: dict, address: str) -> int:
    is_ipv4 = ":" not in address
    if _looks_online(entry):
        return _PRIORITY_ONLINE_IPV4 if is_ipv4 else _PRIORITY_ONLINE_IPV6
    return _PRIORITY_UNKNOWN_IPV4 if is_ipv4 else _PRIORITY_UNKNOWN_IPV6


def _looks_online(entry: dict) -> bool:
    for key in _STATUS_KEYS:
        value = entry.get(key)
        if value is None:
            continue
        return str(value).strip().lower() in _ONLINE_MARKERS
    return False


def _normalize_address(raw_value: str) -> str | None:
    candidate = raw_value.strip().split("/")[0].strip()
    if not candidate:
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _iter_dicts(payload: object) -> Iterator[dict]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _iter_dicts(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_dicts(item)

