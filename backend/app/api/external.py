from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.models import Resource, ApiKey, TelegramPushRecord
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
    text: str


class CallbackRequest(BaseModel):
    resource_id: int
    status: str  # success / failed
    error_message: Optional[str] = None
    message_id: Optional[str] = None
    response_payload: Optional[dict] = None


def build_push_text(resource: Resource) -> str:
    link = resource.new_share_link or resource.original_link
    return "\n".join([
        f"名称：{resource.name}",
        f"标签：{resource.tags or ''}",
        f"链接：{link or ''}",
    ])


def build_push_item(resource: Resource) -> PushItem:
    return PushItem(
        id=resource.id,
        name=resource.name,
        tags=resource.tags,
        share_link=resource.new_share_link,
        extract_code=resource.new_extract_code,
        transferred_at=resource.transferred_at,
        text=build_push_text(resource),
    )


@router.get("/push/health")
async def health(api_key: ApiKey = Depends(verify_api_key)):
    return {"status": "ok", "key_name": api_key.name}


@router.get("/push/pending")
async def get_pending(
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(verify_api_key),
):
    result = await db.execute(
        select(Resource)
        .where(Resource.status == "推送队列")
        .order_by(Resource.transferred_at.asc())
        .limit(limit)
    )
    resources = result.scalars().all()

    items = [build_push_item(r) for r in resources]

    total_result = await db.execute(
        select(func.count(Resource.id)).where(Resource.status == "推送队列")
    )
    total = total_result.scalar()

    return {"items": items, "total_pending": total}


@router.post("/push/lease")
async def lease_pending(
    limit: int = Query(10, ge=1, le=100),
    retry_stale_minutes: int = Query(30, ge=5, le=1440),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(verify_api_key),
):
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=retry_stale_minutes)
    stale_result = await db.execute(
        select(Resource).where(
            Resource.status == "推送中",
            Resource.pushed_at.is_(None),
            Resource.updated_at < stale_before,
        ).limit(500)
    )
    for resource in stale_result.scalars().all():
        resource.status = "推送失败待重试"
        resource.error_message = "推送领取后超时未回调，已恢复到失败待重试，需在推送管理中重新入队"

    result = await db.execute(
        select(Resource)
        .where(Resource.status == "推送队列")
        .order_by(Resource.transferred_at.asc().nullslast(), Resource.id.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    resources = result.scalars().all()

    now = datetime.now(timezone.utc)
    items = []
    for resource in resources:
        resource.status = "推送中"
        resource.error_message = None
        payload = build_push_item(resource).model_dump(mode="json")
        db.add(TelegramPushRecord(
            resource_id=resource.id,
            status="running",
            push_payload=payload,
            attempt=1,
        ))
        items.append(payload)

    await db.commit()

    total_result = await db.execute(
        select(func.count(Resource.id)).where(Resource.status == "推送队列")
    )
    return {
        "items": items,
        "leased": len(items),
        "total_available": total_result.scalar(),
        "leased_at": now,
    }


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
        resource.error_message = None
    elif req.status == "failed":
        resource.status = "推送失败待重试"
        resource.error_message = req.error_message
    else:
        raise HTTPException(status_code=400, detail="无效状态，需为 success 或 failed")

    record_result = await db.execute(
        select(TelegramPushRecord)
        .where(
            TelegramPushRecord.resource_id == resource.id,
            TelegramPushRecord.status == "running",
        )
        .order_by(TelegramPushRecord.created_at.desc())
        .limit(1)
    )
    record = record_result.scalar_one_or_none()
    if not record:
        record = TelegramPushRecord(resource_id=resource.id, status="pending")
        db.add(record)
    record.status = "success" if req.status == "success" else "failed"
    record.response_payload = {
        "message_id": req.message_id,
        "payload": req.response_payload,
    }
    record.error_message = req.error_message
    record.pushed_at = datetime.now(timezone.utc) if req.status == "success" else None

    await db.commit()
    return {"ok": True, "resource_id": resource.id, "new_status": resource.status}
