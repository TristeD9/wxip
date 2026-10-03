"""iKuai 连接配置与测试接口。"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from app.api.deps import get_storage, require_session
from app.ikuai.client import IKuaiClient, IKuaiError, normalize_base_url
from app.models import IKuaiSettings
from app.storage import AppStorage

router = APIRouter(prefix="/api/ikuai", tags=["ikuai"])


class IKuaiSettingsPayload(BaseModel):
    """前端提交的 iKuai 连接参数。"""

    base_url: str
    username: str = "admin"
    password: str = ""
    verify_tls: bool = True
    timeout_seconds: float = 10.0

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        return normalize_base_url(value)


@router.get("/settings")
async def read_ikuai_settings(
    storage: AppStorage = Depends(get_storage), _session: str = Depends(require_session)
) -> dict[str, object]:
    """读取 iKuai 配置，密码只返回是否已设置。"""
    settings = storage.get_ikuai_settings()
    if settings is None:
        return {"configured": False}
    return _describe_settings(settings)


@router.put("/settings")
async def save_ikuai_settings(
    payload: IKuaiSettingsPayload,
    storage: AppStorage = Depends(get_storage),
    _session: str = Depends(require_session),
) -> dict[str, object]:
    """保存 iKuai 配置，密码留空表示沿用已保存的密码。"""
    existing = storage.get_ikuai_settings()
    password = payload.password or (existing.password if existing else "")
    settings = IKuaiSettings(
        base_url=payload.base_url,
        username=payload.username,
        password=password,
        verify_tls=payload.verify_tls,
        timeout_seconds=payload.timeout_seconds,
    )
    storage.save_ikuai_settings(settings)
    return _describe_settings(settings)


@router.post("/test")
async def test_ikuai_connection(
    storage: AppStorage = Depends(get_storage), _session: str = Depends(require_session)
) -> dict[str, object]:
    """登录 iKuai 并返回解析到的公网 IP。"""
    settings = _require_settings(storage)
    try:
        async with IKuaiClient(settings) as client:
            address = await client.get_public_ip()
    except (IKuaiError, httpx.HTTPError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return {"ok": True, "public_ip": address}


@router.post("/probe")
async def probe_ikuai(
    storage: AppStorage = Depends(get_storage), _session: str = Depends(require_session)
) -> dict[str, object]:
    """返回所有 WAN 查询方式的原始响应，便于按固件版本适配。"""
    settings = _require_settings(storage)
    try:
        async with IKuaiClient(settings) as client:
            probes = await client.probe()
    except (IKuaiError, httpx.HTTPError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return {"probes": [probe.model_dump() for probe in probes]}


def _require_settings(storage: AppStorage) -> IKuaiSettings:
    settings = storage.get_ikuai_settings()
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="尚未配置 iKuai 连接参数"
        )
    return settings


def _describe_settings(settings: IKuaiSettings) -> dict[str, object]:
    return {
        "configured": True,
        "base_url": settings.base_url,
        "username": settings.username,
        "password_set": bool(settings.password),
        "verify_tls": settings.verify_tls,
        "timeout_seconds": settings.timeout_seconds,
    }
