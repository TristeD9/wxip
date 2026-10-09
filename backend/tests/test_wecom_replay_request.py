"""重放可信 IP 请求的成败判定与登录态校验。"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models import RequestTemplate, WeComLoginState
from app.wecom.admin_browser import WeComAdminError, WeComAdminSession

FRAME_URL = "https://work.weixin.qq.com/wework_admin/frame#/apps"
LOGIN_URL = "https://work.weixin.qq.com/wework_admin/loginpage_wx?from=myhome"
SUCCESS_BODY = '{"errcode":0,"errmsg":"ok"}'


class FakeResponse:
    def __init__(self, *, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body


class FakeRequestContext:
    """记录重放出去的请求，并返回预设响应。"""

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def fetch(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class FakePage:
    """只实现登录态校验用到的页面动作。"""

    def __init__(self, *, redirect_to: str | None = None) -> None:
        self.url = FRAME_URL
        self.redirect_to = redirect_to
        self.closed = False

    async def goto(self, url: str, **kwargs) -> None:
        if self.redirect_to is not None:
            self.url = self.redirect_to

    async def wait_for_load_state(self, state: str, timeout: int | None = None) -> None:
        return None

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


class FakeBrowserContext:
    def __init__(self, *, response: FakeResponse, page: FakePage | None = None) -> None:
        self.request = FakeRequestContext(response)
        self.pages: list[FakePage] = []
        self._page = page

    async def new_page(self) -> FakePage:
        assert self._page is not None, "测试只预设了一个页面"
        self.pages.append(self._page)
        return self._page

    async def storage_state(self, path: str) -> None:
        return None


def build_session(
    context: FakeBrowserContext, state_path: Path, *, status: str = "logged_in"
) -> WeComAdminSession:
    """构造一个已经注入浏览器上下文的会话，避免真的启动 Chromium。"""
    session = WeComAdminSession(
        state_path=state_path,
        headless=True,
        channel="",
        timeout_ms=1_000,
        apps_url_provider=lambda: FRAME_URL,
    )
    session._context = context
    session._login_state = WeComLoginState(
        status=status, message="", updated_at=datetime.now(timezone.utc)
    )
    return session


def build_template() -> RequestTemplate:
    return RequestTemplate(
        method="POST",
        url="https://work.weixin.qq.com/wework_admin/apps/saveIpConfig",
        body="app_id={app_id}&ipList%5B%5D={ip}",
    )


async def test_replay_request_returns_body_when_wecom_accepts(tmp_path):
    context = FakeBrowserContext(response=FakeResponse(status=200, body=SUCCESS_BODY))
    session = build_session(context, tmp_path / "state.json")

    text = await session.replay_request(
        build_template(), agent_id="1230006", app_id="5629500000000001", ip="9.9.9.9"
    )

    assert text == SUCCESS_BODY
    url, kwargs = context.request.calls[0]
    assert url == "https://work.weixin.qq.com/wework_admin/apps/saveIpConfig"
    assert kwargs["data"] == "app_id=5629500000000001&ipList%5B%5D=9.9.9.9"


async def test_replay_request_raises_when_wecom_returns_errcode(tmp_path):
    body = '{"errcode":301002,"errmsg":"invalid url_token"}'
    context = FakeBrowserContext(response=FakeResponse(status=200, body=body))
    session = build_session(context, tmp_path / "state.json")

    with pytest.raises(WeComAdminError, match="errcode=301002"):
        await session.replay_request(
            build_template(), agent_id="1230006", app_id="5629500000000001", ip="9.9.9.9"
        )


async def test_replay_request_raises_on_http_error(tmp_path):
    context = FakeBrowserContext(response=FakeResponse(status=502, body="bad gateway"))
    session = build_session(context, tmp_path / "state.json")

    with pytest.raises(WeComAdminError, match="HTTP 502"):
        await session.replay_request(
            build_template(), agent_id="1230006", app_id="5629500000000001", ip="9.9.9.9"
        )


async def test_ensure_logged_in_fails_when_backend_redirects_to_login(tmp_path):
    page = FakePage(redirect_to=LOGIN_URL)
    context = FakeBrowserContext(response=FakeResponse(status=200, body=SUCCESS_BODY), page=page)
    session = build_session(context, tmp_path / "state.json")

    with pytest.raises(WeComAdminError, match="重新扫码"):
        await session.ensure_logged_in()

    assert session.login_state().status == "failed"
    assert page.closed is True


async def test_ensure_logged_in_accepts_cached_state_after_checking_backend(tmp_path):
    page = FakePage()
    context = FakeBrowserContext(response=FakeResponse(status=200, body=SUCCESS_BODY), page=page)
    session = build_session(context, tmp_path / "state.json", status="idle")

    await session.ensure_logged_in()

    assert session.login_state().status == "logged_in"
    assert page.closed is True
