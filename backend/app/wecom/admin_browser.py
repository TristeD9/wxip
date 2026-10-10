"""用 Playwright 驱动企业微信管理后台：扫码登录、发现应用、重放可信 IP 请求。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Response
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from app.models import RequestTemplate, WeComApp, WeComLoginState
from app.wecom.curl_template import filter_replay_headers
from app.wecom.parsing import describe_wecom_error, extract_self_built_apps, extract_trusted_ips

logger = logging.getLogger(__name__)

LOGIN_URL = "https://work.weixin.qq.com/wework_admin/loginpage_wx?from=myhome"
FRAME_URL_FRAGMENT = "wework_admin/frame"
NETWORK_IDLE_TIMEOUT_MS = 8_000

QR_FRAME_SELECTOR = "iframe[src*='login_qrcode']"

_QR_FRAME_ELEMENT_SELECTORS = ("img", "canvas")
_QR_PAGE_ELEMENT_SELECTORS = (
    "img.ww_login_qrcode",
    ".login_qrcode img",
    "[class*='qrcode'] img",
    "img[src^='data:image']",
)
_QR_PAGE_CONTAINER_SELECTORS = (".ww_wechatQrCode", "#wx_reg")
_RECORDED_RESOURCE_TYPES = {"xhr", "fetch", "document"}
_MAX_RECORDED_BODY_CHARS = 200_000
_DEBUG_FILE_NAME = "wecom_discover_debug.json"
_READ_DEBUG_FILE_NAME = "wecom_read_debug.json"
# 会话失效时后台返回的是登录页网页，用这些特征把它和正常 JSON 响应区分开
_LOGIN_PAGE_MARKERS = ("loginpage_wx", "login_qrcode", "ww_login_qrcode", "扫码登录")


class WeComAdminError(RuntimeError):
    """企业微信管理后台自动化失败。"""


class WeComAdminSession:
    """持有唯一的浏览器上下文，供登录、发现应用与请求重放共用。"""

    def __init__(
        self,
        *,
        state_path: Path,
        headless: bool,
        channel: str,
        timeout_ms: int,
        apps_url_provider: Callable[[], str],
    ) -> None:
        self._state_path = state_path
        self._headless = headless
        self._channel = channel
        self._timeout_ms = timeout_ms
        self._apps_url_provider = apps_url_provider
        self._operation_lock = asyncio.Lock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._login_task: asyncio.Task | None = None
        self._login_page: Page | None = None
        self._login_state = WeComLoginState(status="idle", updated_at=datetime.now(timezone.utc))

    def login_state(self) -> WeComLoginState:
        """返回当前登录状态快照。"""
        return self._login_state

    async def start_login(self) -> WeComLoginState:
        """打开管理后台登录页并抓取二维码，随后在后台等待扫码结果。"""
        async with self._operation_lock:
            await self._ensure_browser()
            await self._discard_previous_login_page()
            page = await self._require_context().new_page()
            self._login_page = page
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=self._timeout_ms)

            if self._is_admin_frame(page.url):
                await self._mark_logged_in()
                await page.close()
                return self._login_state

            qr_png_base64 = await self._capture_qr(page)
            self._set_state("waiting_scan", qr_png_base64=qr_png_base64, message="请使用企业微信扫码")
            self._login_task = asyncio.create_task(self._wait_for_login(page))
            return self._login_state

    async def ensure_logged_in(self) -> None:
        """确认管理后台登录态仍有效，失效时抛出可读异常。"""
        async with self._operation_lock:
            await self._ensure_logged_in_locked(verify_session=True)

    async def discover_apps(self) -> list[WeComApp]:
        """打开应用管理页，从后台自身的 XHR 响应中提取自建应用清单。"""
        if self._operation_lock.locked():
            raise WeComAdminError("上一次自动发现还在进行中，请稍候再试")
        async with self._operation_lock:
            await self._ensure_logged_in_locked()
            context = self._require_context()
            page = self._authenticated_page()
            created_page = page is None
            if page is None:
                page = await context.new_page()
            recorder = _ResponseRecorder()
            context.on("response", recorder.handle_response)
            try:
                for candidate_url in self._candidate_apps_urls():
                    if page.url == candidate_url:
                        # 已经在目标地址时 goto 不会产生网络请求，必须强制刷新
                        await page.reload(wait_until="domcontentloaded", timeout=self._timeout_ms)
                    else:
                        await page.goto(
                            candidate_url, wait_until="domcontentloaded", timeout=self._timeout_ms
                        )
                    await _wait_for_network_idle(page)
                    await recorder.drain()
                    apps = recorder.extract_apps()
                    if apps:
                        # 成功也留一份记录，便于核对抓到的到底是哪些应用
                        await self._dump_discovery_debug(page, recorder)
                        return apps
                if not self._is_admin_frame(page.url):
                    raise WeComAdminError("企业微信管理后台登录态已失效，请重新扫码登录后再试")
                # 必须在页面还开着的时候留档，否则拿不到标题和正文
                await self._dump_discovery_debug(page, recorder)
            finally:
                context.remove_listener("response", recorder.handle_response)
                await recorder.drain()
                if created_page:
                    await page.close()

            raise WeComAdminError(
                f"未能在应用管理页捕获到自建应用列表（已记录 {len(recorder.records)} 个响应，"
                "详情见 data/wecom_discover_debug.json），或在页面中手工粘贴应用清单"
            )

    def _candidate_apps_urls(self) -> list[str]:
        configured = self._apps_url_provider()
        frame_root = "https://work.weixin.qq.com/wework_admin/frame"
        # 新版后台用 #/apps 形式的路由，旧的 #apps 会被重定向回首页
        candidates = [configured, f"{frame_root}#/apps", frame_root]
        return list(dict.fromkeys(candidates))

    async def _dump_discovery_debug(self, page: Page, recorder: _ResponseRecorder) -> None:
        """把发现失败时的页面与响应摘要写盘，便于按真实结构适配。"""
        try:
            body_text = await page.inner_text("body")
        except PlaywrightError:
            body_text = ""
        try:
            page_title = await page.title()
        except PlaywrightError:
            page_title = ""
        payload = {
            "page_url": page.url,
            "page_title": page_title,
            "body_text_head": body_text[:1500],
            "responses": [
                {key: value for key, value in record.items() if key != "payload"}
                for record in recorder.records
            ],
        }
        try:
            self._state_path.parent.joinpath(_DEBUG_FILE_NAME).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as error:
            logger.warning("写入自动发现调试文件失败：%s", error)

    async def replay_request(
        self, template: RequestTemplate, *, agent_id: str, app_id: str, ip: str
    ) -> str:
        """用管理后台的登录态重放录制好的请求。"""
        async with self._operation_lock:
            await self._ensure_logged_in_locked()
            context = self._require_context()
            rendered = template.render(agent_id=agent_id, app_id=app_id, ip=ip)
            headers = filter_replay_headers(rendered.headers)
            if rendered.body is not None and not _has_header(headers, "content-type"):
                headers["Content-Type"] = "application/json"
            try:
                response = await context.request.fetch(
                    rendered.url,
                    method=rendered.method,
                    headers=headers,
                    data=rendered.body,
                    timeout=self._timeout_ms,
                )
            except PlaywrightError as error:
                raise WeComAdminError(f"重放可信 IP 请求失败：{error}") from error
            text = await response.text()
            if response.status >= 400:
                raise WeComAdminError(
                    f"企业微信返回 HTTP {response.status}：{text[:200]}"
                )
            # 登录态失效时后台会把登录页网页当成接口响应返回，HTTP 状态同样是 200
            if _looks_like_login_page(text):
                self._set_state("failed", message="企业微信登录态已失效，请重新扫码")
                raise WeComAdminError("企业微信返回了登录页，登录态已失效，请重新扫码登录")
            if _looks_like_html(text):
                raise WeComAdminError("企业微信返回的是网页而不是接口 JSON，请重新录制请求模板")
            # 后台拒绝写入时同样是 200，只把原因写在响应体里，必须解析出来
            error_detail = describe_wecom_error(text)
            if error_detail is not None:
                raise WeComAdminError(f"企业微信拒绝了本次请求：{error_detail}")
            return text

    async def read_trusted_ips(
        self, template: RequestTemplate, *, agent_id: str, app_id: str, ip: str
    ) -> list[str] | None:
        """读取该应用当前的可信 IP；解析不出来时返回 None 并把原始响应留档。"""
        text = await self.replay_request(template, agent_id=agent_id, app_id=app_id, ip=ip)
        trusted_ips = extract_trusted_ips(text)
        if trusted_ips is None:
            await self._dump_read_debug(agent_id=agent_id, response_text=text)
        return trusted_ips

    async def _dump_read_debug(self, *, agent_id: str, response_text: str) -> None:
        """把读不出可信 IP 的响应写盘，便于按真实结构补解析规则。"""
        payload = {
            "agent_id": agent_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "response_sample": response_text[:4000],
        }
        try:
            self._state_path.parent.joinpath(_READ_DEBUG_FILE_NAME).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as error:
            logger.warning("写入可信 IP 读取调试文件失败：%s", error)

    async def _ensure_logged_in_locked(self, *, verify_session: bool = False) -> None:
        """在已持有操作锁的情况下确认登录态，必要时用已保存的登录态恢复。

        ``verify_session`` 为真时，即使进程内状态已是「已登录」也重新访问一次后台，
        否则企业微信侧会话过期后，内存里的陈旧状态会一直骗过后面的请求。
        """
        if self._login_state.status == "logged_in" and not verify_session:
            return
        await self._ensure_browser()
        context = self._require_context()
        page = self._authenticated_page()
        created_page = page is None
        if page is None:
            page = await context.new_page()
        try:
            await page.goto(
                self._apps_url_provider(), wait_until="domcontentloaded", timeout=self._timeout_ms
            )
            # 登录态失效时后台会跳回登录页，等网络安静下来再判断，避免误判成已登录
            await _wait_for_network_idle(page)
            if not self._is_admin_frame(page.url) or await self._page_shows_login(page):
                self._set_state("failed", message="企业微信登录态已失效，请重新扫码")
                raise WeComAdminError("企业微信登录态已失效，请重新扫码登录")
            await self._mark_logged_in()
        finally:
            if created_page:
                await page.close()

    @staticmethod
    async def _page_shows_login(page: Page) -> bool:
        """页面里出现登录二维码就说明会话已失效（此时 URL 可能仍停在 frame）。"""
        try:
            return await page.locator(QR_FRAME_SELECTOR).count() > 0
        except PlaywrightError as error:
            logger.debug("检测登录页失败：%s", error)
            return False

    def _authenticated_page(self) -> Page | None:
        """返回当前已登录管理后台的标签页，优先使用扫码时那个页面。"""
        pages = self._context.pages if self._context is not None else []
        return select_authenticated_page(self._login_page, pages)

    async def close(self) -> None:
        """关闭浏览器与 Playwright，进程退出时调用。"""
        if self._login_task is not None:
            self._login_task.cancel()
            try:
                await self._login_task
            except (asyncio.CancelledError, PlaywrightError):
                pass
            self._login_task = None
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _ensure_browser(self) -> None:
        if self._context is not None:
            return
        try:
            self._playwright = await async_playwright().start()
            launch_options: dict[str, object] = {
                "headless": self._headless,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if self._channel:
                # 本机没有 Playwright 自带 Chromium 时，直接复用系统 Chrome / Edge
                launch_options["channel"] = self._channel
            self._browser = await self._playwright.chromium.launch(**launch_options)
        except (PlaywrightError, OSError) as error:
            raise WeComAdminError(
                "Chromium 启动失败，非 Docker 部署请先执行 playwright install chromium。"
                f"原始错误：{error}"
            ) from error
        storage_state = str(self._state_path) if self._state_path.exists() else None
        self._context = await self._browser.new_context(
            storage_state=storage_state, locale="zh-CN", viewport={"width": 1440, "height": 900}
        )
        self._context.set_default_timeout(self._timeout_ms)

    async def _wait_for_login(self, page: Page) -> None:
        context = self._require_context()
        deadline = asyncio.get_running_loop().time() + self._timeout_ms / 1000
        while asyncio.get_running_loop().time() < deadline:
            for candidate in context.pages:
                if self._is_admin_frame(candidate.url):
                    self._login_page = candidate
                    await self._mark_logged_in()
                    return
            await asyncio.sleep(1)
        self._set_state("failed", message="扫码超时，请重新生成登录二维码")
        await self._close_page(page)

    async def _mark_logged_in(self) -> None:
        context = self._context
        if context is not None:
            await context.storage_state(path=str(self._state_path))
        self._set_state("logged_in", message="已登录企业微信管理后台")

    async def _capture_qr(self, page: Page) -> str:
        """二维码位于 login_qrcode 跨域 iframe 里，先取 iframe 内的图片再退回容器截图。"""
        qr_frame = page.frame_locator(QR_FRAME_SELECTOR)
        for selector in _QR_FRAME_ELEMENT_SELECTORS:
            captured = await _screenshot_first_visible(qr_frame.locator(selector))
            if captured:
                return captured
        for selector in _QR_PAGE_ELEMENT_SELECTORS + _QR_PAGE_CONTAINER_SELECTORS:
            captured = await _screenshot_first_visible(page.locator(selector))
            if captured:
                return captured
        raise WeComAdminError(
            "未能在登录页找到二维码，可能是企业微信改版或触发了安全验证，请打开浏览器可视化模式后重试"
        )

    def _set_state(self, status: str, **updates: object) -> None:
        payload = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
            "qr_png_base64": self._login_state.qr_png_base64,
            "message": "",
        }
        payload.update(updates)
        self._login_state = WeComLoginState.model_validate(payload)

    def _require_context(self) -> BrowserContext:
        if self._context is None:
            raise WeComAdminError("浏览器会话尚未初始化，请先执行扫码登录")
        return self._context

    async def _discard_previous_login_page(self) -> None:
        """重复点击扫码时取消上一轮等待并关掉旧二维码，避免页面堆积。"""
        if self._login_task is not None and not self._login_task.done():
            self._login_task.cancel()
        self._login_task = None
        previous_page = self._login_page
        self._login_page = None
        if previous_page is not None:
            await self._close_page(previous_page)

    @staticmethod
    async def _close_page(page: Page) -> None:
        try:
            if not page.is_closed():
                await page.close()
        except PlaywrightError as error:
            logger.debug("关闭登录页失败：%s", error)

    @staticmethod
    def _is_admin_frame(url: str) -> bool:
        return FRAME_URL_FRAGMENT in url


class _ResponseRecorder:
    """收集后台页面的响应，用于发现应用列表，失败时也能留档排查。"""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self._tasks: set[asyncio.Task] = set()

    def handle_response(self, response: Response) -> None:
        if response.request.resource_type not in _RECORDED_RESOURCE_TYPES:
            return
        if response.status != 200:
            return
        self._tasks.add(asyncio.create_task(self._capture(response)))

    async def drain(self) -> None:
        if not self._tasks:
            return
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def extract_apps(self) -> list[WeComApp]:
        for record in self.records:
            payload = record.get("payload")
            if payload is None:
                continue
            apps = extract_self_built_apps(payload)
            if apps:
                return apps
        return []

    async def _capture(self, response: Response) -> None:
        try:
            body = await response.text()
        except PlaywrightError:
            return
        body = body[:_MAX_RECORDED_BODY_CHARS]
        lowered = body.lower()
        payload: object | None = None
        if "agentid" in lowered or "app_id" in lowered:
            try:
                payload = json.loads(body)
            except ValueError:
                payload = None
        self.records.append(
            {
                "url": response.url,
                "resource_type": response.request.resource_type,
                "content_type": (response.headers or {}).get("content-type", ""),
                "length": len(body),
                "has_agentid": "agentid" in lowered,
                "has_app_id": "app_id" in lowered,
                "matched_keys": [
                    key
                    for key in ("agentid", "agent_id", "app_id", "appId", "agentId")
                    if key.lower() in lowered
                ],
                "preview": body[:300],
                "payload_preview": body[:2000] if "app_id" in lowered else "",
                "app_entry_samples": _sample_app_entries(payload),
                "payload": payload,
            }
        )


def _sample_app_entries(payload: object, limit: int = 3) -> list[dict[str, str]]:
    """从响应里挑出前几条疑似应用条目，只保留字段名与短值，便于排障。"""
    samples: list[dict[str, str]] = []
    for entry in _iter_mapping_dicts(payload):
        if not any(str(key).lower() in {"app_id", "appid", "agentid", "agent_id"} for key in entry):
            continue
        samples.append(
            {
                str(key): (
                    str(value)[:60]
                    if isinstance(value, (str, int, float, bool)) or value is None
                    else f"<{type(value).__name__}>"
                )
                for key, value in list(entry.items())[:20]
            }
        )
        if len(samples) >= limit:
            break
    return samples


def _iter_mapping_dicts(payload: object):
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _iter_mapping_dicts(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_mapping_dicts(item)


async def _screenshot_first_visible(locator) -> str | None:
    """截图第一个可见元素，找不到或截图失败时返回 None 交给下一个策略。"""
    target = locator.first
    try:
        await target.wait_for(state="visible", timeout=5_000)
        png_bytes = await target.screenshot()
    except (PlaywrightTimeoutError, PlaywrightError) as error:
        logger.debug("二维码候选元素不可用：%s", error)
        return None
    return base64.b64encode(png_bytes).decode("ascii")


async def _wait_for_network_idle(page: Page) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        logger.debug("等待应用管理页网络空闲超时，继续解析已捕获的响应")


def _has_header(headers: dict[str, str], name: str) -> bool:
    return any(key.lower() == name.lower() for key in headers)


def _looks_like_html(body: str) -> bool:
    """接口本应返回 JSON，返回网页基本意味着请求没落到真接口上。"""
    return body.lstrip().startswith("<")


def _looks_like_login_page(body: str) -> bool:
    """按特征判断响应体是不是企业微信登录页。"""
    lowered = body.lower()
    return any(marker in lowered for marker in _LOGIN_PAGE_MARKERS)


def select_authenticated_page(login_page: Page | None, pages: list[Page]) -> Page | None:
    """在候选标签页里挑出真正登录了管理后台的那个。"""
    if login_page is not None and not login_page.is_closed():
        if WeComAdminSession._is_admin_frame(login_page.url):
            return login_page
    for candidate in pages:
        if candidate.is_closed():
            continue
        if WeComAdminSession._is_admin_frame(candidate.url):
            return candidate
    return None
