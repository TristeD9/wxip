"""自动发现用到的响应记录器。"""

from app.wecom.admin_browser import _ResponseRecorder


def test_response_recorder_returns_parsed_payloads():
    recorder = _ResponseRecorder()
    payload = {"data": {"list": [{"agentid": 1230006, "name": "客服系统"}]}}
    recorder.records.append({"url": "https://work.weixin.qq.com/wework_admin/x", "payload": payload})
    recorder.records.append({"url": "https://example.com", "payload": None})

    assert recorder.payloads() == [payload]


def test_response_recorder_returns_empty_without_payloads():
    recorder = _ResponseRecorder()
    recorder.records.append({"url": "https://example.com", "payload": None})

    assert recorder.payloads() == []
