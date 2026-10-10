"""把浏览器复制的 cURL 命令转成可复用的请求模板。"""

from __future__ import annotations

import json
import re
import shlex

from app.models import (
    AGENT_ID_PLACEHOLDER,
    APP_ID_PLACEHOLDER,
    IP_PLACEHOLDER,
    RequestTemplate,
)

_IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_AGENT_ID_QUERY_PATTERN = re.compile(r"(?i)\b(agent_?id)=(\d{3,12})")
_AGENT_ID_JSON_PATTERN = re.compile(r'(?i)"(agent_?id)"\s*:\s*(\d{3,12})')
_AGENT_ID_JSON_STRING_PATTERN = re.compile(r'(?i)"(agent_?id)"\s*:\s*"(\d{3,12})"')
_APP_ID_QUERY_PATTERN = re.compile(r"(?i)\b(app_?id)=(\d{3,20})")
_APP_ID_JSON_PATTERN = re.compile(r'(?i)"(app_?id)"\s*:\s*(\d{3,20})')
_APP_ID_JSON_STRING_PATTERN = re.compile(r'(?i)"(app_?id)"\s*:\s*"(\d{3,20})"')
_NUMERIC_CANDIDATE_PATTERN = re.compile(r"\b\d{4,20}\b")

_VALUE_FLAGS = {
    "-X",
    "--request",
    "-H",
    "--header",
    "-d",
    "--data",
    "--data-raw",
    "--data-binary",
    "--data-urlencode",
    "-b",
    "--cookie",
    "-u",
    "--user",
    "-A",
    "--user-agent",
    "-e",
    "--referer",
    "--url",
    "--connect-timeout",
    "--max-time",
}
# 这些头由浏览器会话自己提供；录进模板只会带来过期 Cookie 或长度不匹配
DROP_ON_REPLAY_HEADERS = frozenset(
    {
        "cookie",
        "host",
        "content-length",
        "connection",
        "accept-encoding",
        "accept-language",
        "priority",
        "user-agent",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "sec-fetch-dest",
        "sec-fetch-mode",
        "sec-fetch-site",
    }
)

_BOOLEAN_FLAGS = {
    "--compressed",
    "-k",
    "--insecure",
    "-s",
    "--silent",
    "-S",
    "--show-error",
    "-L",
    "--location",
    "-v",
    "--verbose",
    "-i",
    "--include",
    "-g",
    "--globoff",
    "--no-buffer",
}


class CurlParseError(ValueError):
    """cURL 命令无法解析。"""


def validate_request_template(template: RequestTemplate) -> list[str]:
    """校验模板能否用于覆盖可信 IP，并返回提醒。

    Raises:
        CurlParseError: 模板中没有任何可替换的公网 IP 位置。
    """
    haystack = _template_haystack(template)
    if IP_PLACEHOLDER not in haystack:
        raise CurlParseError(
            f"请求中未找到公网 IP 位置，请在地址或请求体里手工保留一个 {IP_PLACEHOLDER} 占位符"
        )
    warnings: list[str] = []
    if AGENT_ID_PLACEHOLDER not in haystack and APP_ID_PLACEHOLDER not in haystack:
        candidates = _find_numeric_candidates(haystack)
        hint = f"，请求中出现的数字有：{'、'.join(candidates)}" if candidates else ""
        warnings.append(
            f"请求中未找到应用编号占位符{hint}。"
            f"如果其中包含应用编号，请在模板 JSON 里把它手工改成 {AGENT_ID_PLACEHOLDER} 或 {APP_ID_PLACEHOLDER}，"
            "否则所有应用都会写入同一份配置"
        )
    return warnings


def validate_read_template(template: RequestTemplate) -> list[str]:
    """校验查询可信 IP 的模板能否逐个应用读取。

    Raises:
        CurlParseError: 模板里没有任何应用编号占位符，那样每个应用都会读到同一份配置。
    """
    haystack = _template_haystack(template)
    if AGENT_ID_PLACEHOLDER not in haystack and APP_ID_PLACEHOLDER not in haystack:
        raise CurlParseError(
            f"读取请求里没有 {AGENT_ID_PLACEHOLDER} 或 {APP_ID_PLACEHOLDER} 占位符，"
            "无法逐个应用读取当前可信 IP"
        )
    return []


def required_placeholders(template: RequestTemplate) -> set[str]:
    """返回模板里实际用到的编号占位符，供同步前检查应用是否有对应编号。"""
    haystack = _template_haystack(template)
    return {
        placeholder
        for placeholder in (AGENT_ID_PLACEHOLDER, APP_ID_PLACEHOLDER)
        if placeholder in haystack
    }


def _template_haystack(template: RequestTemplate) -> str:
    """把模板的可搜索部分拼成一段文本，供占位符检查复用。"""
    return " ".join(
        [template.url, template.body or "", json.dumps(template.headers, ensure_ascii=False)]
    )


def parse_curl_command(command: str, *, known_agent_ids: list[str] | None = None) -> RequestTemplate:
    """把 cURL 命令解析成请求模板，并把可变部分替换为占位符。

    Args:
        command: 从浏览器开发者工具复制的 cURL 命令，支持 bash 与 cmd 换行。
        known_agent_ids: 已知的 agentid 列表，用于替换成 ``{agent_id}`` 占位符。

    Raises:
        CurlParseError: 命令不是 cURL、缺少 URL 或引号不闭合。
    """
    tokens = _tokenize(command)
    method: str | None = None
    url: str | None = None
    headers: dict[str, str] = {}
    body: str | None = None

    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token in ("curl", "curl.exe"):
            continue
        if token == "--":
            if index < len(tokens):
                url = tokens[index]
                index += 1
            continue
        if token.startswith("-"):
            name, inline_value = _split_flag(token)
            value = inline_value if inline_value is not None else _take_value(tokens, index, name)
            if inline_value is None and value is not None:
                index += 1
            if name in ("-X", "--request") and value:
                method = value.upper()
            elif name in ("-H", "--header") and value:
                _store_header(headers, value)
            elif name in ("-b", "--cookie") and value:
                headers["Cookie"] = value
            elif name in ("-u", "--user") and value:
                headers.setdefault("Authorization", f"Basic {value}")
            elif name in ("-A", "--user-agent") and value:
                headers["User-Agent"] = value
            elif name in ("-e", "--referer") and value:
                headers["Referer"] = value
            elif name in ("--url",) and value:
                url = value
            elif name in ("-d", "--data", "--data-raw", "--data-binary", "--data-urlencode") and value:
                body = value
            elif name not in _VALUE_FLAGS and name not in _BOOLEAN_FLAGS and not name.startswith("--"):
                continue
            continue
        if url is None:
            url = token

    if url is None:
        raise CurlParseError("未能从命令中解析出请求 URL")

    method = method or ("POST" if body else "GET")
    return RequestTemplate(
        method=method,
        url=_apply_placeholders(url, known_agent_ids or []),
        headers=filter_replay_headers(
            {
                key: _apply_placeholders(value, known_agent_ids or [])
                for key, value in headers.items()
            }
        ),
        body=None if body is None else _apply_placeholders(body, known_agent_ids or []),
    )


def mask_header_values(headers: dict[str, str]) -> dict[str, str]:
    """隐藏请求头中的凭据，用于前端预览。"""
    masked: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in {"cookie", "authorization", "x-csrf-token"}:
            masked[key] = f"{value[:12]}***（已隐藏）" if value else value
        else:
            masked[key] = value
    return masked


def filter_replay_headers(headers: dict[str, str]) -> dict[str, str]:
    """剔除不该随模板保存或重放的请求头。"""
    return {
        key: value for key, value in headers.items() if key.lower() not in DROP_ON_REPLAY_HEADERS
    }


def _tokenize(command: str) -> list[str]:
    text = command.strip()
    if not text:
        raise CurlParseError("cURL 命令为空")
    normalized = re.sub(r"(\^|\\|`)\s*\r?\n", " ", text)
    normalized = _unescape_cmd_curl(normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized.startswith("curl"):
        raise CurlParseError("请提供以 curl 开头的命令")
    try:
        return shlex.split(normalized, posix=True)
    except ValueError as error:
        raise CurlParseError(f"cURL 命令引号不闭合：{error}") from error


def _split_flag(token: str) -> tuple[str, str | None]:
    if token.startswith("--") and "=" in token:
        name, _, value = token.partition("=")
        return name, value
    return token, None


def _unescape_cmd_curl(text: str) -> str:
    """还原 Chrome “Copy as cURL (cmd)” 的 ^ 转义，bash 格式不受影响。

    cmd 版片段里 ^ 一律是转义前缀（包括 ^& 、^%% 以及包裹引号用的 ^"），
    复制过程中还可能残留成 ^%^5B 这种形式，这里统一按 %XX 还原再去掉 ^。
    """
    if '^"' not in text:
        return text
    unescaped = text.replace('^"', '"')
    unescaped = re.sub(r"\^%\^([0-9A-Fa-f]{2})", r"%\1", unescaped)
    return unescaped.replace("^", "")


def _take_value(tokens: list[str], index: int, name: str) -> str | None:
    if name not in _VALUE_FLAGS:
        return None
    if index >= len(tokens):
        return None
    return tokens[index]


def _store_header(headers: dict[str, str], raw_header: str) -> None:
    if ":" not in raw_header:
        return
    key, _, value = raw_header.partition(":")
    headers[key.strip()] = value.strip()


def _apply_placeholders(text: str, known_agent_ids: list[str]) -> str:
    result = _IPV4_PATTERN.sub(IP_PLACEHOLDER, text)
    for agent_id in known_agent_ids:
        if agent_id:
            result = result.replace(agent_id, AGENT_ID_PLACEHOLDER)
    result = _AGENT_ID_QUERY_PATTERN.sub(rf"\1={AGENT_ID_PLACEHOLDER}", result)
    result = _AGENT_ID_JSON_STRING_PATTERN.sub(rf'"\1":"{AGENT_ID_PLACEHOLDER}"', result)
    result = _AGENT_ID_JSON_PATTERN.sub(rf'"\1":{AGENT_ID_PLACEHOLDER}', result)
    result = _APP_ID_QUERY_PATTERN.sub(rf"\1={APP_ID_PLACEHOLDER}", result)
    result = _APP_ID_JSON_STRING_PATTERN.sub(rf'"\1":"{APP_ID_PLACEHOLDER}"', result)
    return _APP_ID_JSON_PATTERN.sub(rf'"\1":{APP_ID_PLACEHOLDER}', result)


def _find_numeric_candidates(text: str, limit: int = 8) -> list[str]:
    """列出请求里出现的较长数字，帮助用户找到真正的应用编号字段。"""
    return sorted(set(_NUMERIC_CANDIDATE_PATTERN.findall(text)))[:limit]
