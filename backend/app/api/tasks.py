from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, Task

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
    statuses = ["pending", "running", "failed_retryable"]
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
    if task.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="当前状态不支持取消")

    task.status = "skipped"
    await db.commit()
    return {"ok": True}
