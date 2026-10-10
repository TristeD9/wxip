"""cURL 命令解析与模板渲染。"""

import pytest

from app.models import RequestTemplate
from app.wecom.curl_template import (
    CurlParseError,
    mask_header_values,
    parse_curl_command,
    validate_request_template,
)

BASH_CURL = (
    "curl 'https://work.weixin.qq.com/wework_admin/agentSetting/save?agentid=1230002' "
    "-H 'Content-Type: application/json' "
    "-H 'Cookie: sid=super-secret-cookie' "
    "--data-raw '{\"agentid\":1230002,\"trusted_ip_list\":[\"203.0.113.10\"]}'"
)

CMD_CURL = (
    "curl \"https://work.weixin.qq.com/wework_admin/agentSetting/save\" ^\n"
    "  -H \"Content-Type: application/json\" ^\n"
    "  --data-raw \"{\\\"agentid\\\":1230002,\\\"trusted_ip_list\\\":[\\\"203.0.113.10\\\"]}\""
)


def test_parse_bash_curl_extracts_placeholders():
    template = parse_curl_command(BASH_CURL, known_agent_ids=["1230002"])

    assert template.method == "POST"
    assert template.url.endswith("agentid={agent_id}")
    assert "{ip}" in template.body
    assert "{agent_id}" in template.body
    assert template.headers["Content-Type"] == "application/json"


def test_parse_cmd_curl_handles_line_continuation():
    template = parse_curl_command(CMD_CURL, known_agent_ids=["1230002"])

    assert template.method == "POST"
    assert "{ip}" in template.body
    assert "{agent_id}" in template.body


def test_parse_curl_detects_agent_id_without_known_apps():
    template = parse_curl_command(BASH_CURL)

    assert "agentid={agent_id}" in template.url
    assert '"agentid":{agent_id}' in template.body


def test_parse_curl_detects_quoted_agent_id_keeping_string_type():
    command = (
        "curl 'https://work.weixin.qq.com/wework_admin/agentSetting/save?f=json' "
        "-H 'content-type: application/json' "
        "--data-raw '{\"agentid\":\"1230006\",\"trusted_ip_list\":[\"203.0.113.10\"]}'"
    )

    template = parse_curl_command(command)

    assert '"agentid":"{agent_id}"' in template.body


CMD_IP_CONFIG_CURL = (
    'curl ^"https://work.weixin.qq.com/wework_admin/apps/saveIpConfig?lang=zh_CN^&f=json^&ajax=1'
    '^&timeZoneInfo^%^5Bzone_offset^%^5D=-8^" ^\n'
    '  -H ^"^accept: application/json, text/javascript, */*; q=0.01^" ^\n'
    '  -H ^"^content-type: application/x-www-form-urlencoded^" ^\n'
    '  --data-raw ^"^app_id=5629500000000001^&ipList^%^5B^%^5D=203.0.113.10^"'
)


def test_parse_cmd_curl_normalizes_escaping():
    template = parse_curl_command(CMD_IP_CONFIG_CURL)

    assert template.url == (
        "https://work.weixin.qq.com/wework_admin/apps/saveIpConfig"
        "?lang=zh_CN&f=json&ajax=1&timeZoneInfo%5Bzone_offset%5D=-8"
    )
    assert template.headers["content-type"] == "application/x-www-form-urlencoded"
    assert template.headers["accept"] == "application/json, text/javascript, */*; q=0.01"
    assert template.body == "app_id={app_id}&ipList%5B%5D={ip}"


def test_parse_cmd_curl_marks_app_id_placeholder():
    warnings = validate_request_template(parse_curl_command(CMD_IP_CONFIG_CURL))

    assert warnings == []


def test_parse_curl_rejects_non_curl_command():
    with pytest.raises(CurlParseError, match="curl"):
        parse_curl_command("wget https://example.com")


def test_parse_curl_rejects_command_without_url():
    with pytest.raises(CurlParseError, match="URL"):
        parse_curl_command("curl -X POST -H 'A: b'")


def test_validate_request_template_requires_ip_placeholder():
    template = RequestTemplate(method="POST", url="https://example.com/save", body='{"ip":"1.1.1.1"}')

    with pytest.raises(CurlParseError, match="\\{ip\\}"):
        validate_request_template(template)


def test_validate_request_template_warns_without_agent_placeholder():
    template = RequestTemplate(method="POST", url="https://example.com/save", body='{"ips":["{ip}"]}')

    warnings = validate_request_template(template)

    assert len(warnings) == 1
    assert "{agent_id}" in warnings[0]


def test_validate_request_template_lists_numeric_candidates():
    template = RequestTemplate(
        method="POST",
        url="https://example.com/save?corpappid=1230006",
        body='{"ips":["{ip}"],"ids":["77"]}',
    )

    warnings = validate_request_template(template)

    assert "1230006" in warnings[0]


def test_mask_header_values_hides_cookie():
    masked = mask_header_values({"Cookie": "sid=super-secret-cookie", "Accept": "application/json"})

    assert masked["Accept"] == "application/json"
    assert "super-secret-cookie" not in masked["Cookie"]


def test_parse_curl_does_not_store_session_cookie():
    template = parse_curl_command(BASH_CURL, known_agent_ids=["1230002"])

    assert "Cookie" not in template.headers
    assert template.headers["Content-Type"] == "application/json"


def test_render_request_substitutes_both_placeholders():
    template = RequestTemplate(
        method="POST",
        url="https://example.com/save?agentid={agent_id}",
        headers={"X-Ip": "{ip}"},
        body='{"agentid":{agent_id},"trusted_ip_list":["{ip}"]}',
    )

    rendered = template.render(agent_id="1230002", app_id="5629500000000001", ip="8.8.8.8")

    assert rendered.url.endswith("agentid=1230002")
    assert rendered.headers["X-Ip"] == "8.8.8.8"
    assert rendered.body == '{"agentid":1230002,"trusted_ip_list":["8.8.8.8"]}'


def test_render_request_substitutes_console_app_id():
    template = RequestTemplate(
        method="POST",
        url="https://example.com/saveIpConfig",
        body="app_id={app_id}&ipList%5B%5D={ip}",
    )

    rendered = template.render(agent_id="1230006", app_id="5629500000000001", ip="8.8.8.8")

    assert rendered.body == "app_id=5629500000000001&ipList%5B%5D=8.8.8.8"

