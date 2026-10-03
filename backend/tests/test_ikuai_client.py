"""iKuai 登录报文构造与地址规范化。"""

import base64
import hashlib

import pytest

from app.ikuai.client import (
    build_login_form_payload,
    build_login_json_payload,
    normalize_base_url,
    redact_sensitive_values,
)

PASSWORD = "secret-password"


def test_build_login_json_payload_hashes_password():
    md5_password = hashlib.md5(PASSWORD.encode("utf-8")).hexdigest()

    payload = build_login_json_payload("admin", PASSWORD)

    assert payload == {
        "username": "admin",
        "passwd": md5_password,
        "pass": base64.b64encode(md5_password.encode("utf-8")).decode("ascii"),
        "remember_password": 0,
    }


def test_build_login_form_payload_keeps_empty_remember_password():
    payload = build_login_form_payload("admin", PASSWORD)

    assert payload["username"] == "admin"
    assert payload["remember_password"] == ""
    assert payload["passwd"] == hashlib.md5(PASSWORD.encode("utf-8")).hexdigest()


def test_normalize_base_url_adds_scheme_and_strips_trailing_slash():
    assert normalize_base_url(" 192.168.1.1/ ") == "http://192.168.1.1"


def test_normalize_base_url_keeps_existing_scheme():
    assert normalize_base_url("https://ikuai.local:8443/") == "https://ikuai.local:8443"


def test_normalize_base_url_rejects_empty_value():
    with pytest.raises(ValueError, match="不能为空"):
        normalize_base_url("   ")


def test_redact_sensitive_values_hides_pppoe_credentials():
    payload = {
        "Data": {
            "data": [
                {
                    "name": "wan1",
                    "pppoe_ip_addr": "223.5.5.5",
                    "username": "5585127ST@MYADSL",
                    "passwd": "55851271",
                    "lte_pincode": "1234",
                    "bypass_switch": 1,
                }
            ]
        }
    }

    redacted = redact_sensitive_values(payload)
    entry = redacted["Data"]["data"][0]

    assert entry["pppoe_ip_addr"] == "223.5.5.5"
    assert entry["bypass_switch"] == 1
    assert entry["username"] == "***"
    assert entry["passwd"] == "***"
    assert entry["lte_pincode"] == "***"

