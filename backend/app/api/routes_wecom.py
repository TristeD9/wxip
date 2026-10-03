"""企业微信应用清单、请求模板与管理页地址接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_storage, get_wecom_session, require_session
from app.models import RequestTemplate
from app.storage import AppStorage
from app.wecom.admin_browser import WeComAdminError, WeComAdminSession
from app.wecom.curl_template import (
    CurlParseError,
    mask_header_values,
    parse_curl_command,
    validate_request_template,
)
from app.wecom.parsing import merge_app_states, parse_manual_app_list

router = APIRouter(prefix="/api/wecom", tags=["wecom"])


class CurlPayload(BaseModel):
    """前端粘贴的 cURL 命令。"""

    curl: str


class ManualAppsPayload(BaseModel):
    """手工粘贴的应用清单文本。"""

    text: str


class AppsUrlPayload(BaseModel):
    """可自定义的企业微信应用管理页地址。"""

    url: str


class ConsoleAppIdPayload(BaseModel):
    """管理后台里的 16 位应用编号，留空表示清除。"""

    console_app_id: str = ""


@router.get("/apps")
async def list_apps(
    storage: AppStorage = Depends(get_storage), _session: str = Depends(require_session)
) -> dict[str, object]:
    """返回已保存的自建应用清单。"""
    return {"apps": [app.model_dump() for app in storage.list_wecom_apps()]}


@router.post("/apps/discover")
async def discover_apps(
    storage: AppStorage = Depends(get_storage),
    session: WeComAdminSession = Depends(get_wecom_session),
    _session: str = Depends(require_session),
) -> dict[str, object]:
    """从企业微信管理后台自动发现自建应用。"""
    try:
        discovered = await session.discover_apps()
    except WeComAdminError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    merged = merge_app_states(storage.list_wecom_apps(), discovered)
    storage.replace_wecom_apps(merged)
    return {"apps": [app.model_dump() for app in merged]}


@router.put("/apps/manual")
async def save_manual_apps(
    payload: ManualAppsPayload,
    storage: AppStorage = Depends(get_storage),
    _session: str = Depends(require_session),
) -> dict[str, object]:
    """在自动发现失败时，用粘贴的清单兜底。"""
    try:
        parsed = parse_manual_app_list(payload.text)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    merged = merge_app_states(storage.list_wecom_apps(), parsed)
    storage.replace_wecom_apps(merged)
    return {"apps": [app.model_dump() for app in merged]}


@router.put("/apps/{agent_id}/console-app-id")
async def save_console_app_id(
    agent_id: str,
    payload: ConsoleAppIdPayload,
    storage: AppStorage = Depends(get_storage),
    _session: str = Depends(require_session),
) -> dict[str, object]:
    """补录应用在管理后台内部使用的应用编号，供 {app_id} 占位符使用。"""
    existing = storage.list_wecom_apps()
    if not any(app.agent_id == agent_id for app in existing):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="应用不存在")
    console_app_id = payload.console_app_id.strip()
    if console_app_id and not (console_app_id.isdigit() and 3 <= len(console_app_id) <= 20):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="控制台应用编号必须是 3-20 位数字"
        )
    storage.update_app_console_id(agent_id, console_app_id or None)
    return {"apps": [app.model_dump() for app in storage.list_wecom_apps()]}


@router.get("/apps-url")
async def read_apps_url(
    storage: AppStorage = Depends(get_storage), _session: str = Depends(require_session)
) -> dict[str, str]:
    """返回应用管理页地址。"""
    return {"url": storage.get_wecom_apps_url()}


@router.put("/apps-url")
async def save_apps_url(
    payload: AppsUrlPayload,
    storage: AppStorage = Depends(get_storage),
    _session: str = Depends(require_session),
) -> dict[str, str]:
    """保存应用管理页地址，便于企业微信改版后调整。"""
    url = payload.url.strip()
    if not url.startswith("https://work.weixin.qq.com/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="应用管理页地址必须是 work.weixin.qq.com 下的 https 地址",
        )
    storage.save_wecom_apps_url(url)
    return {"url": url}


@router.get("/template")
async def read_template(
    storage: AppStorage = Depends(get_storage), _session: str = Depends(require_session)
) -> dict[str, object]:
    """返回已保存的请求模板。"""
    template = storage.get_request_template()
    if template is None:
        return {"configured": False}
    return _describe_template(template)


@router.post("/template/parse")
async def parse_template(
    payload: CurlPayload,
    storage: AppStorage = Depends(get_storage),
    _session: str = Depends(require_session),
) -> dict[str, object]:
    """解析 cURL 命令，返回带占位符的模板预览，不会保存。"""
    known_agent_ids = [app.agent_id for app in storage.list_wecom_apps()]
    try:
        template = parse_curl_command(payload.curl, known_agent_ids=known_agent_ids)
        warnings = validate_request_template(template)
    except CurlParseError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return {"template": template.model_dump(), "warnings": warnings, "configured": True}


@router.put("/template")
async def save_template(
    payload: RequestTemplate,
    storage: AppStorage = Depends(get_storage),
    _session: str = Depends(require_session),
) -> dict[str, object]:
    """保存请求模板。"""
    try:
        warnings = validate_request_template(payload)
    except CurlParseError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    storage.save_request_template(payload)
    return {**_describe_template(payload), "warnings": warnings}


def _describe_template(template: RequestTemplate) -> dict[str, object]:
    return {
        "configured": True,
        "template": template.model_dump(),
        "headers_preview": mask_header_values(template.headers),
    }
