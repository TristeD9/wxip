"""iKuai 响应解析。"""

from app.ikuai.parser import extract_public_ip, extract_session_key, is_public_ip


def test_extract_public_ip_prefers_online_wan_entry():
    payload = {
        "Result": 10000,
        "data": {
            "data": [
                {"wan_name": "wan1", "ip_addr": "10.0.0.2", "status": "connected"},
                {"wan_name": "wan2", "ip_addr": "1.1.1.1", "status": "down"},
                {"wan_name": "wan3", "ip_addr": "8.8.8.8", "status": "connected"},
            ]
        },
    }

    assert extract_public_ip(payload) == "8.8.8.8"


def test_extract_public_ip_skips_private_and_shared_addresses():
    payload = {"data": {"wan": {"ip_addr": "100.64.1.5", "status": "connected"}}}

    assert extract_public_ip(payload) is None


def test_extract_public_ip_handles_prefix_and_probe_shapes():
    payload = {"data": {"wan_list": [{"ifname": "wan1", "ip": "9.9.9.9/24"}]}}

    assert extract_public_ip(payload) == "9.9.9.9"


def test_extract_public_ip_falls_back_to_ipv6():
    payload = {"data": {"wan": {"ipv4": "192.168.1.1", "ipv6": "2001:4860:4860::8888"}}}

    assert extract_public_ip(payload) == "2001:4860:4860::8888"


def test_extract_session_key_from_nested_payload():
    payload = {"Result": 10000, "data": {"sess_key": "abc123"}}

    assert extract_session_key(payload) == "abc123"


def test_extract_public_ip_from_real_wan_payload_shape():
    payload = {
        "Result": 30000,
        "ErrMsg": "Success",
        "Data": {
            "total": 1,
            "data": [
                {
                    "name": "wan1",
                    "pppoe_status": 2,
                    "pppoe_gateway": "223.5.5.1",
                    "pppoe_netmask": "255.255.255.255",
                    "ip_mask": "",
                    "dhcp_ip_addr": "",
                    "pppoe_ip_addr": "223.5.5.5",
                }
            ],
        },
    }

    assert extract_public_ip(payload) == "223.5.5.5"


def test_extract_public_ip_ignores_non_address_fields():
    payload = {"data": {"ip_mask": "", "pppoe_netmask": "255.255.255.255", "name": "wan1"}}

    assert extract_public_ip(payload) is None


def test_is_public_ip_accepts_only_global_unicast():
    assert is_public_ip("8.8.8.8") is True
    assert is_public_ip("10.0.0.1") is False
    assert is_public_ip("not-an-ip") is False

