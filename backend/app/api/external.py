from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from app.database import get_db
from app.models import Resource, ApiKey
from app.utils.security import hash_api_key

router = APIRouter()


async def verify_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
):
    key_hash = hash_api_key(x_api_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=401, detail="无效的 API 密钥")
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="API 密钥已过期")
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return api_key


class PushItem(BaseModel):
    id: int
    name: str
    tags: Optional[str]
    share_link: Optional[str]
    extract_code: Optional[str]
    transferred_at: Optional[datetime]


class CallbackRequest(BaseModel):
    resource_id: int
    status: str  # success / failed
    error_message: Optional[str] = None
    message_id: Optional[str] = None


@router.get("/push/health")
async def health(api_key: ApiKey = Depends(verify_api_key)):
    return {"status": "ok", "key_name": api_key.name}


@router.get("/push/pending")
async def get_pending(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(verify_api_key),
):
    result = await db.execute(
        select(Resource)
        .where(Resource.status == "待推送")
        .order_by(Resource.transferred_at.asc())
        .limit(limit)
    )
    resources = result.scalars().all()

    items = []
    for r in resources:
        items.append(PushItem(
            id=r.id,
            name=r.name,
            tags=r.tags,
            share_link=r.new_share_link,
            extract_code=r.new_extract_code,
            transferred_at=r.transferred_at,
        ))

    total_result = await db.execute(
        select(func.count(Resource.id)).where(Resource.status == "待推送")
    )
    total = total_result.scalar()

    return {"items": items, "total_pending": total}


@router.post("/push/callback")
async def push_callback(
    req: CallbackRequest,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(verify_api_key),
):
    result = await db.execute(
        select(Resource).where(Resource.id == req.resource_id)
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")

    if req.status == "success":
        resource.status = "已推送"
        resource.pushed_at = datetime.now(timezone.utc)
    elif req.status == "failed":
        resource.status = "推送失败待重试"
        resource.error_message = req.error_message
    else:
        raise HTTPException(status_code=400, detail="无效状态，需为 success 或 failed")

    await db.commit()
    return {"ok": True, "resource_id": resource.id, "new_status": resource.status}
