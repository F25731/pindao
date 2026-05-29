from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, Resource, TelegramPushRecord

router = APIRouter()


class PushRecordOut(BaseModel):
    id: int
    resource_id: int
    status: str
    attempt: int
    error_message: Optional[str]
    pushed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/pending")
async def list_pending_push(
    page: int = 0,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(Resource)
        .where(Resource.status == "待推送")
        .order_by(Resource.transferred_at.asc())
        .offset(page * page_size)
        .limit(page_size)
    )
    resources = result.scalars().all()
    total_result = await db.execute(
        select(func.count(Resource.id)).where(Resource.status == "待推送")
    )
    total = total_result.scalar()
    return {"items": resources, "total": total}


@router.get("/history", response_model=List[PushRecordOut])
async def push_history(
    page: int = 0,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(TelegramPushRecord)
        .order_by(TelegramPushRecord.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    return result.scalars().all()


@router.post("/push")
async def manual_push(
    resource_ids: List[int],
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """手动将指定资源标记为待推送。"""
    result = await db.execute(
        select(Resource).where(
            Resource.id.in_(resource_ids),
            Resource.status == "转存成功",
        )
    )
    resources = result.scalars().all()
    count = 0
    for r in resources:
        r.status = "待推送"
        count += 1
    await db.commit()
    return {"ok": True, "queued": count}


@router.get("/stats")
async def push_stats(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    statuses = ["待推送", "推送中", "已推送", "推送失败待重试", "推送最终失败"]
    counts = {}
    for s in statuses:
        result = await db.execute(
            select(func.count(Resource.id)).where(Resource.status == s)
        )
        counts[s] = result.scalar()
    return counts
