"""从企业微信后台返回的数据中提取自建应用清单，并识别接口返回的错误说明。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from app.models import WeComApp

_AGENT_ID_KEYS = ("agentid", "agent_id", "agentId", "agent")
_CONSOLE_APP_ID_KEYS = ("app_id", "appid", "appId")
_APP_OPEN_ID_KEYS = ("app_open_id", "appOpenId")
_NAME_KEYS = ("name", "agent_name", "agentName", "app_name", "appName", "title", "nickname", "nick_name")
_AGENT_ID_PATTERN = re.compile(r"^\d{3,20}$")
_CONSOLE_APP_ID_PATTERN = re.compile(r"^\d{3,20}$")
_SELF_BUILT_AGENT_OPEN_ID_PATTERN = re.compile(r"^1\d{5,6}$")
_SELF_BUILT_APP_MARKERS = ("callback_url", "url_token", "callback_aeskey")
_WECOM_OK_ERRCODE = 0


def describe_wecom_error(body: str) -> str | None:
    """从企业微信接口响应里取出失败说明。

    管理后台接口失败时 HTTP 状态码仍是 200，错误只写在响应体的 ``errcode`` 里，
    因此必须解析响应体才能区分"真的写进去了"和"被后台拒绝了"。

    Args:
        body: 接口返回的响应体文本。

    Returns:
        失败时返回 ``errcode=.. msg=..`` 形式的说明；成功、非 JSON 或缺少
        ``errcode`` 字段时返回 ``None``。
    """
    text = body.strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    if not isinstance(payload, dict) or "errcode" not in payload:
        return None
    errcode = payload["errcode"]
    if errcode == _WECOM_OK_ERRCODE or str(errcode).strip() == "0":
        return None
    errmsg = str(payload.get("errmsg") or "").strip()
    if not errmsg:
        return f"errcode={errcode}"
    return f"errcode={errcode} msg={errmsg}"


def extract_self_built_apps(payload: object) -> list[WeComApp]:
    """递归扫描 JSON，收集自建应用。

    新版管理后台的 ``getCorpApplication`` 把自建应用、系统应用（通讯录同步助手、
    外部联系人）和腾讯官方应用混在同一个列表里，只能靠 ``app_open_id`` 区分：
    自建应用的 ``app_open_id`` 就是 agentid（1 开头），系统与官方应用是 2、3 开头。

    注意 ``aes_app_id`` 在自建应用上同样存在，不能作为排除条件。
    """
    discovered: dict[str, WeComApp] = {}
    for entry in _iter_dicts(payload):
        if not _looks_like_self_built_app(entry):
            continue
        agent_id = _read_agent_id(entry) or _read_agent_open_id(entry)
        if agent_id is None:
            continue
        name = _read_name(entry)
        if name is None:
            continue
        discovered.setdefault(
            agent_id,
            WeComApp(agent_id=agent_id, name=name, console_app_id=_read_console_app_id(entry)),
        )
    return sorted(discovered.values(), key=lambda app: int(app.agent_id))


def merge_app_states(existing: list[WeComApp], discovered: list[WeComApp]) -> list[WeComApp]:
    """用最新发现结果覆盖清单，同时保留每个应用已有的同步状态。"""
    previous = {app.agent_id: app for app in existing}
    merged: list[WeComApp] = []
    for app in discovered:
        stored = previous.get(app.agent_id)
        if stored is None:
            merged.append(app)
            continue
        merged.append(
            app.model_copy(
                update={
                    "console_app_id": app.console_app_id or stored.console_app_id,
                    "last_synced_ip": stored.last_synced_ip,
                    "last_synced_at": stored.last_synced_at,
                    "last_error": stored.last_error,
                }
            )
        )
    return merged


def parse_manual_app_list(text: str) -> list[WeComApp]:
    """解析手工粘贴的应用清单。

    每行格式为 ``agentid,应用名`` / ``agentid 应用名``，可选第三列填管理后台的
    16 位应用编号：``agentid,应用名,console_app_id``。

    Raises:
        ValueError: 某一行缺少 agentid 或应用名，或第三列不是数字。
    """
    apps: list[WeComApp] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = re.split(r"[\s,，\t]+", line, maxsplit=1)
        if len(parts) != 2 or not _AGENT_ID_PATTERN.match(parts[0].strip()):
            raise ValueError(
                f"第 {line_number} 行格式不正确，应为：agentid,应用名 或 agentid,应用名,控制台应用编号"
            )
        name = parts[1].strip()
        console_app_id: str | None = None
        trailing_id = re.match(r"^(.*)[,，]\s*(\d{3,20})$", name)
        if trailing_id:
            name, console_app_id = trailing_id.group(1).strip(), trailing_id.group(2)
        if not name:
            raise ValueError(f"第 {line_number} 行缺少应用名")
        if console_app_id and not _CONSOLE_APP_ID_PATTERN.match(console_app_id):
            raise ValueError(f"第 {line_number} 行的控制台应用编号必须是数字")
        apps.append(WeComApp(agent_id=parts[0].strip(), name=name, console_app_id=console_app_id))
    if not apps:
        raise ValueError("应用清单为空")
    return apps


def _read_agent_id(entry: dict) -> str | None:
    for key in _AGENT_ID_KEYS:
        value = entry.get(key)
        if isinstance(value, bool) or value is None:
            continue
        text = str(value).strip()
        if _AGENT_ID_PATTERN.match(text):
            return text
    return None


def _read_name(entry: dict) -> str | None:
    for key in _NAME_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _read_console_app_id(entry: dict) -> str | None:
    """读取管理后台内部的应用编号（形如 5629500000000001），它与 agentid 不同。"""
    for key in _CONSOLE_APP_ID_KEYS:
        value = entry.get(key)
        if isinstance(value, bool) or value is None:
            continue
        text = str(value).strip()
        if _CONSOLE_APP_ID_PATTERN.match(text):
            return text
    return None


def _read_agent_open_id(entry: dict) -> str | None:
    """自建应用的 ``app_open_id`` 就是 agentid，用它补全缺失的 agentid。"""
    for key in _APP_OPEN_ID_KEYS:
        value = entry.get(key)
        if isinstance(value, bool) or value is None:
            continue
        text = str(value).strip()
        if _SELF_BUILT_AGENT_OPEN_ID_PATTERN.match(text):
            return text
    return None


def _looks_like_self_built_app(entry: dict) -> bool:
    """排除企业微信内置应用与腾讯官方应用，只保留管理员自建的应用。"""
    open_id = _read_text(entry, _APP_OPEN_ID_KEYS)
    if open_id:
        return bool(_SELF_BUILT_AGENT_OPEN_ID_PATTERN.match(open_id))
    if _read_agent_id(entry):
        return True
    return any(_has_text(entry, key) for key in _SELF_BUILT_APP_MARKERS)


def _read_text(entry: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (str, int)):
            text = str(value).strip()
            if text:
                return text
    return None


def _has_text(entry: dict, key: str) -> bool:
    value = entry.get(key)
    if isinstance(value, bool) or value is None:
        return False
    return bool(str(value).strip())


def _iter_dicts(payload: object) -> Iterator[dict]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _iter_dicts(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_dicts(item)
