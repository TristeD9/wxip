"""重放请求头的过滤规则。"""

from app.wecom.curl_template import filter_replay_headers


def test_filter_replay_headers_drops_recorded_cookie():
    headers = {
        "Cookie": "sid=stale-session",
        "Content-Length": "42",
        "Host": "work.weixin.qq.com",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }

    filtered = filter_replay_headers(headers)

    assert "Cookie" not in filtered
    assert "Content-Length" not in filtered
    assert "Host" not in filtered
    assert filtered["Content-Type"] == "application/json"
    assert filtered["X-Requested-With"] == "XMLHttpRequest"
