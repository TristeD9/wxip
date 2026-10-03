"""管理员登录、首次初始化、改密与企业微信扫码接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import (
    get_login_throttle,
    get_settings,
    get_storage,
    get_wecom_session,
    require_session,
)
from app.config import Settings
from app.login_throttle import LoginThrottle
from app.models import WeComLoginState
from app.passwords import check_password_strength, hash_password, verify_password
from app.security import create_session_token
from app.storage import AppStorage
from app.wecom.admin_browser import WeComAdminError, WeComAdminSession

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_USERNAME_LENGTH = 32


class SetupPayload(BaseModel):
    """首次部署时创建管理员账号。"""

    username: str
    password: str
    password_confirm: str


class LoginPayload(BaseModel):
    """管理员账号密码登录。"""

    username: str
    password: str


class PasswordChangePayload(BaseModel):
    """修改管理员密码。"""

    current_password: str
    new_password: str
    new_password_confirm: str


@router.get("/setup/status")
async def read_setup_status(storage: AppStorage = Depends(get_storage)) -> dict[str, bool]:
    """返回面板是否已经创建过管理员账号。"""
    return {"initialized": storage.count_admins() > 0}


@router.post("/setup")
async def create_first_admin(
    payload: SetupPayload,
    storage: AppStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    throttle: LoginThrottle = Depends(get_login_throttle),
) -> dict[str, object]:
    """创建唯一的管理员账号，创建成功后直接签发登录令牌。"""
    if storage.count_admins() > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="管理员账号已存在，请直接登录")
    username = payload.username.strip()
    problem = _validate_new_credentials(username, payload.password, payload.password_confirm)
    if problem:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=problem)
    if not storage.create_admin_if_absent(username, hash_password(payload.password)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="管理员账号已存在，请直接登录")
    throttle.reset(username)
    return _issue_token(settings, username)


@router.post("/login")
async def login(
    payload: LoginPayload,
    storage: AppStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    throttle: LoginThrottle = Depends(get_login_throttle),
) -> dict[str, object]:
    """用管理员账号密码登录，连续失败会被临时锁定。"""
    username = payload.username.strip()
    locked_seconds = throttle.locked_seconds_left(username)
    if locked_seconds > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"登录失败次数过多，请 {locked_seconds} 秒后再试",
        )
    admin = storage.get_admin(username)
    if admin is None or not verify_password(payload.password, admin.password_hash):
        throttle.record_failure(username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码不正确")
    throttle.reset(username)
    return _issue_token(settings, username)


@router.get("/me")
async def read_current_admin(username: str = Depends(require_session)) -> dict[str, str]:
    """返回当前登录的管理员用户名。"""
    return {"username": username}


@router.post("/password")
async def change_password(
    payload: PasswordChangePayload,
    username: str = Depends(require_session),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, bool]:
    """校验当前密码后更新为新密码。"""
    admin = storage.get_admin(username)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在，请重新登录")
    if not verify_password(payload.current_password, admin.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")
    if payload.new_password != payload.new_password_confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="两次输入的新密码不一致")
    problem = check_password_strength(payload.new_password)
    if problem:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=problem)
    storage.update_admin_password(username, hash_password(payload.new_password))
    return {"ok": True}


@router.post("/wecom/login", response_model=WeComLoginState)
async def start_wecom_login(
    session: WeComAdminSession = Depends(get_wecom_session),
    _session: str = Depends(require_session),
) -> WeComLoginState:
    """打开企业微信管理后台登录页并返回扫码二维码。"""
    try:
        return await session.start_login()
    except WeComAdminError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


@router.get("/wecom/login", response_model=WeComLoginState)
async def read_wecom_login(
    session: WeComAdminSession = Depends(get_wecom_session),
    _session: str = Depends(require_session),
) -> WeComLoginState:
    """返回当前企业微信扫码登录状态。"""
    return session.login_state()


def _validate_new_credentials(username: str, password: str, password_confirm: str) -> str | None:
    if not username:
        return "用户名不能为空"
    if len(username) > MAX_USERNAME_LENGTH:
        return f"用户名不能超过 {MAX_USERNAME_LENGTH} 个字符"
    if password != password_confirm:
        return "两次输入的密码不一致"
    return check_password_strength(password)


def _issue_token(settings: Settings, username: str) -> dict[str, object]:
    token = create_session_token(settings.secret_key, settings.session_ttl_seconds, subject=username)
    return {"token": token, "username": username, "expires_in": settings.session_ttl_seconds}
