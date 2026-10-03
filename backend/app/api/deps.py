"""FastAPI 依赖：从 app.state 取出服务，并校验面板会话。"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from app.config import Settings
from app.login_throttle import LoginThrottle
from app.models import SyncSettings
from app.security import read_session_token
from app.services.scheduler import SyncScheduler
from app.services.sync_service import SyncService
from app.storage import AppStorage
from app.wecom.admin_browser import WeComAdminSession

SESSION_COOKIE_NAME = "panel_session"


def get_settings(request: Request) -> Settings:
    """返回进程级配置。"""
    return request.app.state.settings


def get_storage(request: Request) -> AppStorage:
    """返回 SQLite 存储。"""
    return request.app.state.storage


def get_sync_service(request: Request) -> SyncService:
    """返回同步服务。"""
    return request.app.state.sync_service


def get_scheduler(request: Request) -> SyncScheduler:
    """返回后台定时任务。"""
    return request.app.state.scheduler


def get_wecom_session(request: Request) -> WeComAdminSession:
    """返回企业微信管理后台浏览器会话。"""
    return request.app.state.wecom_session


def get_default_sync_settings(request: Request) -> SyncSettings:
    """返回进程启动时的同步默认值。"""
    return request.app.state.default_sync_settings


def get_login_throttle(request: Request) -> LoginThrottle:
    """返回登录失败节流器。"""
    return request.app.state.login_throttle


async def require_session(
    request: Request, authorization: str | None = Header(default=None)
) -> str:
    """校验 Bearer 令牌或 Cookie，返回当前管理员用户名。

    Raises:
        HTTPException: 会话缺失、签名不合法、已过期，或账号已被删除。
    """
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        token = request.cookies.get(SESSION_COOKIE_NAME, "")
    username = read_session_token(get_settings(request).secret_key, token)
    if not username or get_storage(request).get_admin(username) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="会话无效或已过期，请重新登录"
        )
    return username

