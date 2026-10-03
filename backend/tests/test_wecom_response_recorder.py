"""自动发现用到的响应记录器。"""

from app.wecom.admin_browser import _ResponseRecorder


def test_response_recorder_extracts_apps_from_captured_payload():
    recorder = _ResponseRecorder()
    recorder.records.append(
        {
            "url": "https://work.weixin.qq.com/wework_admin/apps/list",
            "payload": {"data": {"list": [{"agentid": 1230006, "name": "客服系统"}]}},
        }
    )

    apps = recorder.extract_apps()

    assert [app.agent_id for app in apps] == ["1230006"]


def test_response_recorder_returns_empty_when_no_payload_has_apps():
    recorder = _ResponseRecorder()
    recorder.records.append({"url": "https://example.com", "payload": {"Result": 0}})
    recorder.records.append({"url": "https://example.com/2", "payload": None})

    assert recorder.extract_apps() == []
