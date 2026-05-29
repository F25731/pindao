from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, Resource, Task

router = APIRouter()


class ResourceOut(BaseModel):
    id: int
    batch_id: Optional[int]
    name: str
    tags: Optional[str]
    original_link: str
    share_id: Optional[str]
    extract_code: Optional[str]
    status: str
    transfer_account_id: Optional[int]
    new_share_link: Optional[str]
    new_extract_code: Optional[str]
    error_message: Optional[str]
    retry_count: int
    created_at: datetime
    transferred_at: Optional[datetime]
    pushed_at: Optional[datetime]

    class Config:
        from_attributes = True


class ResourceListResponse(BaseModel):
    items: List[ResourceOut]
    total: int
    page: int
    page_size: int


@router.get("", response_model=ResourceListResponse)
async def list_resources(
    page: int = 0,
    page_size: int = 20,
    status: Optional[str] = None,
    batch_id: Optional[int] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    query = select(Resource)
    count_query = select(func.count(Resource.id))

    if status:
        query = query.where(Resource.status == status)
        count_query = count_query.where(Resource.status == status)
    if batch_id:
        query = query.where(Resource.batch_id == batch_id)
        count_query = count_query.where(Resource.batch_id == batch_id)
    if search:
        query = query.where(Resource.name.ilike(f"%{search}%"))
        count_query = count_query.where(Resource.name.ilike(f"%{search}%"))

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    result = await db.execute(
        query.order_by(Resource.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()

    return ResourceListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{resource_id}", response_model=ResourceOut)
async def get_resource(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(select(Resource).where(Resource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")
    return resource


@router.post("/{resource_id}/retry")
async def retry_resource(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(select(Resource).where(Resource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")
    if resource.status not in ("最终失败", "失败待重试"):
        raise HTTPException(status_code=400, detail="当前状态不支持重试")

    resource.status = "待转存"
    resource.retry_count = 0
    resource.error_message = None
    resource.error_response = None

    # 重置关联任务
    task_result = await db.execute(select(Task).where(Task.resource_id == resource_id))
    task = task_result.scalar_one_or_none()
    if task:
        task.status = "pending"
        task.attempt = 0
        task.error_message = None
        task.error_response = None
        task.checkpoint = None
        task.next_retry_at = None

    await db.commit()
    return {"ok": True, "status": resource.status}


@router.post("/batch-retry")
async def batch_retry(
    resource_ids: List[int],
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(Resource).where(
            Resource.id.in_(resource_ids),
            Resource.status.in_(("最终失败", "失败待重试")),
        )
    )
    resources = result.scalars().all()
    count = 0
    for resource in resources:
        resource.status = "待转存"
        resource.retry_count = 0
        resource.error_message = None
        resource.error_response = None
        count += 1

    await db.commit()
    return {"ok": True, "retried": count}
