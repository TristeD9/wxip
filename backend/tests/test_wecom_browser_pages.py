"""管理后台标签页选择逻辑。"""

from app.wecom.admin_browser import select_authenticated_page

FRAME_URL = "https://work.weixin.qq.com/wework_admin/frame#apps"
LOGIN_URL = "https://work.weixin.qq.com/wework_admin/loginpage_wx?from=myhome"


class FakePage:
    def __init__(self, url: str, *, closed: bool = False) -> None:
        self.url = url
        self._closed = closed

    def is_closed(self) -> bool:
        return self._closed


def test_select_authenticated_page_prefers_login_page():
    login_page = FakePage(FRAME_URL)
    other_page = FakePage("https://example.com")

    selected = select_authenticated_page(login_page, [other_page, login_page])

    assert selected is login_page


def test_select_authenticated_page_skips_page_still_on_login():
    login_page = FakePage(LOGIN_URL)
    frame_page = FakePage("https://work.weixin.qq.com/wework_admin/frame#index")

    selected = select_authenticated_page(login_page, [login_page, frame_page])

    assert selected is frame_page


def test_select_authenticated_page_ignores_closed_pages():
    closed = FakePage(FRAME_URL, closed=True)

    assert select_authenticated_page(closed, [closed]) is None


def test_select_authenticated_page_returns_none_without_admin_frame():
    assert select_authenticated_page(FakePage(LOGIN_URL), [FakePage(LOGIN_URL)]) is None
