from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, Resource, Task

router = APIRouter()


class TaskOut(BaseModel):
    id: int
    resource_id: int
    task_type: str
    status: str
    account_id: Optional[int]
    attempt: int
    max_attempts: int
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    next_retry_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    items: List[TaskOut]
    total: int


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    page: int = 0,
    page_size: int = 20,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    query = select(Task)
    count_query = select(func.count(Task.id))

    if status:
        query = query.where(Task.status == status)
        count_query = count_query.where(Task.status == status)
    if task_type:
        query = query.where(Task.task_type == task_type)
        count_query = count_query.where(Task.task_type == task_type)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    result = await db.execute(
        query.order_by(Task.created_at.desc()).offset(page * page_size).limit(page_size)
    )
    items = result.scalars().all()
    return TaskListResponse(items=items, total=total)


@router.get("/queue-status")
async def queue_status(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    statuses = ["pending", "running", "pause_requested", "paused", "failed_retryable", "failed_final", "success", "skipped"]
    counts = {}
    for s in statuses:
        result = await db.execute(
            select(func.count(Task.id)).where(Task.status == s)
        )
        counts[s] = result.scalar()
    return counts


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("pending", "running", "failed_retryable", "pause_requested", "paused"):
        raise HTTPException(status_code=400, detail="当前状态不支持取消")

    if task.status == "running":
        checkpoint = task.checkpoint or {}
        checkpoint["cancel_requested"] = True
        task.checkpoint = checkpoint
        task.status = "cancel_requested"
    else:
        task.status = "skipped"
        task.completed_at = datetime.now(timezone.utc)

    result = await db.execute(select(Resource).where(Resource.id == task.resource_id))
    resource = result.scalar_one_or_none()
    if resource:
        resource.status = "已取消"

    await db.commit()
    return {"ok": True}


@router.post("/{task_id}/pause")
async def pause_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("pending", "running", "failed_retryable", "pause_requested", "paused"):
        raise HTTPException(status_code=400, detail="当前状态不支持暂停")

    if task.status == "running":
        checkpoint = task.checkpoint or {}
        checkpoint["pause_requested"] = True
        task.checkpoint = checkpoint
        task.status = "pause_requested"
    else:
        task.status = "paused"

    result = await db.execute(select(Resource).where(Resource.id == task.resource_id))
    resource = result.scalar_one_or_none()
    if resource:
        resource.status = "转存暂停"

    await db.commit()
    return {"ok": True, "status": task.status}


@router.post("/{task_id}/resume")
async def resume_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("paused", "pause_requested"):
        raise HTTPException(status_code=400, detail="当前状态不支持恢复")

    checkpoint = task.checkpoint or {}
    checkpoint.pop("pause_requested", None)
    checkpoint.pop("cancel_requested", None)
    task.checkpoint = checkpoint
    task.status = "pending"
    task.next_retry_at = None

    result = await db.execute(select(Resource).where(Resource.id == task.resource_id))
    resource = result.scalar_one_or_none()
    if resource:
        resource.status = "待转存"

    await db.commit()
    return {"ok": True, "status": task.status}
