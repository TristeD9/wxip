"""企业微信后台响应解析。"""

import pytest

from app.models import WeComApp
from app.wecom.parsing import (
    describe_wecom_error,
    extract_app_trusted_ips,
    extract_self_built_apps,
    extract_trusted_ips,
    merge_app_states,
    parse_manual_app_list,
)


def test_extract_self_built_apps_dedupes_and_sorts():
    payload = {
        "data": {
            "agentlist": [
                {"agentid": 1230002, "name": "客服系统"},
                {"agentid": 1230001, "name": "订单系统"},
                {"agentid": 1230002, "name": "客服系统"},
            ]
        }
    }

    apps = extract_self_built_apps(payload)

    assert [app.agent_id for app in apps] == ["1230001", "1230002"]
    assert apps[1].name == "客服系统"


def test_extract_self_built_apps_ignores_entries_without_name():
    payload = {"list": [{"agentid": 1230003}, {"name": "无编号应用"}]}

    assert extract_self_built_apps(payload) == []


SELF_BUILT_ENTRY = {
    "corp_id": "1970325000000001",
    "app_id": "5629500000000002",
    "app_open_id": "1230002",
    "name": "示例应用",
    "callback_url": "https://example.com/callback",
    "url_token": "example-url-token",
    "callback_aeskey": "secret-key",
}

CONTACTS_ASSISTANT_ENTRY = {
    "app_id": "5629500000000003",
    "app_open_id": "2000002",
    "name": "通讯录同步助手",
    "aes_app_id": "wwauthdb7862b83a72e8e1230002",
}

EXTERNAL_CONTACT_ENTRY = {
    "app_id": "5629500000000004",
    "app_open_id": "2000003",
    "name": "外部联系人",
    "aes_app_id": "wwauthdb7862b83a72e8e1230003",
}

TENCENT_APP_ENTRY = {
    "app_id": "5629500000000005",
    "app_open_id": "3010001",
    "name": "公告",
    "app_developer": "腾讯科技股份有限公司",
    "business_id": "10001",
}


def test_extract_self_built_app_maps_console_ids():
    payload = {"corp_app_list": [SELF_BUILT_ENTRY]}

    apps = extract_self_built_apps(payload)

    assert len(apps) == 1
    assert apps[0].agent_id == "1230002"
    assert apps[0].console_app_id == "5629500000000002"
    assert apps[0].name == "示例应用"


def test_extract_self_built_app_keeps_entry_with_aes_app_id():
    """真实响应里自建应用同样带 aes_app_id，不能因此被过滤掉。"""
    entry = dict(SELF_BUILT_ENTRY, aes_app_id="wwauthdb7862b83a72e8e1230002")

    apps = extract_self_built_apps({"openapi_app": [entry]})

    assert [app.agent_id for app in apps] == ["1230002"]


def test_extract_self_built_app_accepts_integer_app_open_id():
    """真实响应里 app_open_id 有时是数字而不是字符串。"""
    entry = {"app_id": "5629500000000001", "app_open_id": 1230006, "name": "每日推送"}

    apps = extract_self_built_apps({"openapi_app": [entry]})

    assert apps[0].agent_id == "1230006"
    assert apps[0].console_app_id == "5629500000000001"


@pytest.mark.parametrize(
    "entry", [CONTACTS_ASSISTANT_ENTRY, EXTERNAL_CONTACT_ENTRY, TENCENT_APP_ENTRY]
)
def test_extract_skips_system_and_official_apps(entry):
    payload = {"corp_app_list": [SELF_BUILT_ENTRY, entry]}

    apps = extract_self_built_apps(payload)

    assert [app.name for app in apps] == ["示例应用"]


def test_extract_apps_accepts_long_agent_id():
    payload = {"list": [{"agentid": "5629500000000001", "name": "客服系统"}]}

    apps = extract_self_built_apps(payload)

    assert apps[0].agent_id == "5629500000000001"
    assert apps[0].console_app_id is None


def test_extract_apps_accepts_title_as_name():
    payload = {"list": [{"agentid": 1230006, "title": "订单系统"}]}

    apps = extract_self_built_apps(payload)

    assert apps[0].name == "订单系统"


def test_merge_app_states_keeps_previous_sync_result():
    existing = [
        WeComApp(agent_id="1230002", name="旧名称", last_synced_ip="8.8.8.8", last_error=None)
    ]
    discovered = [WeComApp(agent_id="1230002", name="客服系统")]

    merged = merge_app_states(existing, discovered)

    assert merged[0].name == "客服系统"
    assert merged[0].last_synced_ip == "8.8.8.8"


def test_parse_manual_app_list_supports_comma_and_space():
    apps = parse_manual_app_list("1230001,订单系统\n1230002 客服系统")

    assert [app.agent_id for app in apps] == ["1230001", "1230002"]
    assert apps[1].name == "客服系统"


def test_parse_manual_app_list_rejects_bad_line():
    with pytest.raises(ValueError, match="第 1 行"):
        parse_manual_app_list("订单系统没有编号")


def test_parse_manual_app_list_rejects_empty_text():
    with pytest.raises(ValueError, match="为空"):
        parse_manual_app_list("   \n  ")


def test_extract_self_built_apps_reads_console_app_id():
    payload = {
        "list": [
            {"agentid": 1230006, "name": "客服系统", "app_id": 5629500000000001},
        ]
    }

    apps = extract_self_built_apps(payload)

    assert apps[0].console_app_id == "5629500000000001"


def test_merge_app_states_keeps_console_app_id_when_discovery_lacks_it():
    existing = [
        WeComApp(agent_id="1230006", name="客服系统", console_app_id="5629500000000001")
    ]
    discovered = [WeComApp(agent_id="1230006", name="客服系统")]

    merged = merge_app_states(existing, discovered)

    assert merged[0].console_app_id == "5629500000000001"


def test_parse_manual_app_list_supports_console_app_id_column():
    apps = parse_manual_app_list("1230006,客服系统,5629500000000001")

    assert apps[0].console_app_id == "5629500000000001"


def test_parse_manual_app_list_keeps_spaces_in_app_name():
    apps = parse_manual_app_list("1230006,客服 系统")

    assert apps[0].name == "客服 系统"
    assert apps[0].console_app_id is None


@pytest.mark.parametrize("body", ['{"errcode":0,"errmsg":"ok"}', '{"errcode":"0","errmsg":"ok"}'])
def test_describe_wecom_error_returns_none_for_success(body):
    assert describe_wecom_error(body) is None


def test_describe_wecom_error_reports_errcode_and_message():
    body = '{"errcode":301002,"errmsg":"invalid url_token"}'

    assert describe_wecom_error(body) == "errcode=301002 msg=invalid url_token"


def test_describe_wecom_error_handles_missing_errmsg():
    assert describe_wecom_error('{"errcode":40001}') == "errcode=40001"


@pytest.mark.parametrize(
    "body",
    [
        "<html><body>login</body></html>",
        '{"Result":0}',
        "not json at all",
        "",
    ],
)
def test_describe_wecom_error_ignores_non_error_bodies(body):
    assert describe_wecom_error(body) is None


@pytest.mark.parametrize(
    "body",
    [
        '{"data":{"trusted_ip_list":["203.0.113.10"]}}',
        '{"data":{"ip_list":["203.0.113.10"]}}',
        '{"data":{"ipList":["203.0.113.10"]}}',
        '{"data":{"trusted_ip":"203.0.113.10"}}',
    ],
)
def test_extract_trusted_ips_reads_known_keys(body):
    assert extract_trusted_ips(body) == ["203.0.113.10"]


def test_extract_trusted_ips_splits_string_value():
    body = '{"ip_list":"203.0.113.10, 203.0.113.11"}'

    assert extract_trusted_ips(body) == ["203.0.113.10", "203.0.113.11"]


def test_extract_trusted_ips_returns_empty_list_when_backend_has_none():
    assert extract_trusted_ips('{"data":{"trusted_ip_list":[]}}') == []


def test_extract_trusted_ips_reads_service_ip_info_list():
    """真实后台返回里企业可信IP 放在 service_ip_info_list。"""
    body = (
        '{"data":{"servicecorp_ip_list":[],"invalid_ip_list":[],'
        '"service_ip_info_list":["203.0.113.10"]}}'
    )

    assert extract_trusted_ips(body) == ["203.0.113.10"]


def test_extract_trusted_ips_reads_object_entries():
    body = (
        '{"data":{"service_ip_info_list":['
        '{"ip":"203.0.113.10","status":1},{"ip":"203.0.113.11","status":0}]}}'
    )

    assert extract_trusted_ips(body) == ["203.0.113.10", "203.0.113.11"]


def test_extract_trusted_ips_returns_empty_for_empty_known_field():
    body = (
        '{"data":{"servicecorp_ip_list":[],"invalid_ip_list":[],'
        '"service_ip_info_list":[]}}'
    )

    assert extract_trusted_ips(body) == []


def test_extract_app_trusted_ips_maps_entries_by_agent_id():
    payload = {
        "data": {
            "openapi_app": [
                {"agentid": 1230002, "name": "客服系统", "ip_list": ["203.0.113.10"]},
                {"agentid": 1230003, "name": "报表系统", "ip_list": []},
            ]
        }
    }

    assert extract_app_trusted_ips(payload) == {"1230002": ["203.0.113.10"], "1230003": []}


def test_extract_app_trusted_ips_learns_field_name_from_sibling_app():
    """字段名不重要：只要有一个应用条目里确实装着 IP，就按同一字段名读其余应用。"""
    payload = {
        "data": {
            "openapi_app": [
                {"agentid": 1230002, "trusted_ip_whitelist": ["203.0.113.10"]},
                {"agentid": 1230003, "trusted_ip_whitelist": ["203.0.113.11", "203.0.113.12"]},
            ]
        }
    }

    assert extract_app_trusted_ips(payload) == {
        "1230002": ["203.0.113.10"],
        "1230003": ["203.0.113.11", "203.0.113.12"],
    }


def test_extract_app_trusted_ips_ignores_system_apps():
    payload = {
        "data": {
            "corp_app_list": [
                {"app_id": "5629500000000003", "app_open_id": "2000002", "ip_list": ["1.1.1.1"]}
            ]
        }
    }

    assert extract_app_trusted_ips(payload) == {}


def test_extract_app_trusted_ips_returns_empty_when_no_entry_holds_ips():
    """所有条目都没有 IP 时返回空字典，表示读不出来，而不是"没有可信 IP"。"""
    payload = {
        "data": {"openapi_app": [{"agentid": 1230002, "name": "客服系统", "ip_list": []}]}
    }

    assert extract_app_trusted_ips(payload) == {}


def test_extract_trusted_ips_falls_back_to_plain_ip_array():
    body = '{"result":{"items":["203.0.113.10","203.0.113.11"]}}'

    assert extract_trusted_ips(body) == ["203.0.113.10", "203.0.113.11"]


@pytest.mark.parametrize(
    "body",
    [
        "<html><body>login</body></html>",
        '{"errcode":0,"errmsg":"ok"}',
        '{"data":{"ip_list":["not-an-ip"]}}',
        '{"data":{"name":"客服系统"}}',
        "not json at all",
    ],
)
def test_extract_trusted_ips_returns_none_when_unreadable(body):
    assert extract_trusted_ips(body) is None
