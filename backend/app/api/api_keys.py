from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, ApiKey
from app.utils.security import generate_api_key, hash_api_key

router = APIRouter()

ALLOWED_API_PERMISSIONS = {
    "push:read",
    "push:callback",
    "search:read",
}


class ApiKeyCreate(BaseModel):
    name: str
    permissions: Optional[List[str]] = None


class ApiKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    permissions: Optional[List[str]]
    is_active: bool
    last_used_at: Optional[datetime]
    created_at: datetime
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


class ApiKeyCreated(BaseModel):
    id: int
    name: str
    key: str
    key_prefix: str


@router.get("", response_model=List[ApiKeyOut])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=ApiKeyCreated)
async def create_api_key(
    req: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    permissions = list(dict.fromkeys(req.permissions or ["push:read", "push:callback"]))
    invalid_permissions = [permission for permission in permissions if permission not in ALLOWED_API_PERMISSIONS]
    if invalid_permissions:
        raise HTTPException(status_code=400, detail=f"不支持的权限: {', '.join(invalid_permissions)}")

    raw_key = generate_api_key()
    key_obj = ApiKey(
        name=req.name,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        permissions=permissions,
        created_by=user.id,
    )
    db.add(key_obj)
    await db.commit()
    await db.refresh(key_obj)
    return ApiKeyCreated(id=key_obj.id, name=key_obj.name, key=raw_key, key_prefix=key_obj.key_prefix)


@router.put("/{key_id}")
async def update_api_key(
    key_id: int,
    name: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key_obj = result.scalar_one_or_none()
    if not key_obj:
        raise HTTPException(status_code=404, detail="API 密钥不存在")
    if name is not None:
        key_obj.name = name
    if is_active is not None:
        key_obj.is_active = is_active
    await db.commit()
    return {"ok": True}


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key_obj = result.scalar_one_or_none()
    if not key_obj:
        raise HTTPException(status_code=404, detail="API 密钥不存在")
    await db.delete(key_obj)
    await db.commit()
    return {"ok": True}
