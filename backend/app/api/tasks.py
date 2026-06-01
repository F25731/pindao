from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, Resource, Task
from app.services.delete_service import delete_resources_permanently

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


class BatchTaskRequest(BaseModel):
    task_ids: List[int]


class BatchDeleteRequest(BaseModel):
    task_ids: List[int]
    mode: str = "task_only"  # task_only / task_and_resource


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


def _set_task_paused(task: Task, resource: Resource | None):
    if task.status == "running":
        checkpoint = task.checkpoint or {}
        checkpoint["pause_requested"] = True
        task.checkpoint = checkpoint
        task.status = "pause_requested"
    elif task.status in ("pending", "failed_retryable", "pause_requested", "paused"):
        task.status = "paused"
    if resource:
        resource.status = "转存暂停"


def _set_task_cancelled(task: Task, resource: Resource | None):
    if task.status == "running":
        checkpoint = task.checkpoint or {}
        checkpoint["cancel_requested"] = True
        task.checkpoint = checkpoint
        task.status = "cancel_requested"
    else:
        task.status = "skipped"
        task.completed_at = datetime.now(timezone.utc)
    if resource:
        resource.status = "已取消"


def _set_task_started(task: Task, resource: Resource | None):
    old_status = task.status
    checkpoint = task.checkpoint or {}
    checkpoint.pop("pause_requested", None)
    checkpoint.pop("cancel_requested", None)
    task.checkpoint = checkpoint
    task.status = "pending"
    task.next_retry_at = None
    task.completed_at = None
    if task.error_message or old_status in ("failed_final", "failed_retryable", "skipped"):
        task.error_message = None
        task.error_response = None
    if resource:
        resource.status = "待转存"


def _set_task_retry(task: Task, resource: Resource | None):
    task.status = "pending"
    task.attempt = 0
    task.error_message = None
    task.error_response = None
    task.checkpoint = None
    task.started_at = None
    task.completed_at = None
    task.next_retry_at = None
    if resource:
        resource.status = "待转存"
        resource.retry_count = 0
        resource.error_message = None
        resource.error_response = None


async def _load_tasks_with_resources(db: AsyncSession, task_ids: List[int]):
    if not task_ids:
        raise HTTPException(status_code=400, detail="请选择任务")
    result = await db.execute(select(Task).where(Task.id.in_(task_ids)))
    tasks = result.scalars().all()
    resource_ids = [task.resource_id for task in tasks]
    resources = {}
    if resource_ids:
        res_result = await db.execute(select(Resource).where(Resource.id.in_(resource_ids)))
        resources = {resource.id: resource for resource in res_result.scalars().all()}
    return tasks, resources


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

    result = await db.execute(select(Resource).where(Resource.id == task.resource_id))
    resource = result.scalar_one_or_none()
    _set_task_cancelled(task, resource)

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

    result = await db.execute(select(Resource).where(Resource.id == task.resource_id))
    resource = result.scalar_one_or_none()
    _set_task_paused(task, resource)

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

    result = await db.execute(select(Resource).where(Resource.id == task.resource_id))
    resource = result.scalar_one_or_none()
    _set_task_started(task, resource)

    await db.commit()
    return {"ok": True, "status": task.status}


@router.post("/batch-pause")
async def batch_pause_tasks(
    req: BatchTaskRequest,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    tasks, resources = await _load_tasks_with_resources(db, req.task_ids)
    count = 0
    for task in tasks:
        if task.status in ("pending", "running", "failed_retryable", "pause_requested", "paused"):
            _set_task_paused(task, resources.get(task.resource_id))
            count += 1
    await db.commit()
    return {"ok": True, "updated": count}


@router.post("/batch-start")
async def batch_start_tasks(
    req: BatchTaskRequest,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    tasks, resources = await _load_tasks_with_resources(db, req.task_ids)
    count = 0
    for task in tasks:
        if task.status in ("paused", "pause_requested", "failed_retryable", "failed_final", "skipped", "pending"):
            if task.status in ("failed_retryable", "failed_final"):
                _set_task_retry(task, resources.get(task.resource_id))
            else:
                _set_task_started(task, resources.get(task.resource_id))
            count += 1
    await db.commit()
    return {"ok": True, "updated": count}


@router.post("/batch-retry")
async def batch_retry_tasks(
    req: BatchTaskRequest,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    tasks, resources = await _load_tasks_with_resources(db, req.task_ids)
    count = 0
    for task in tasks:
        if task.status in ("failed_retryable", "failed_final", "skipped", "paused", "pause_requested"):
            _set_task_retry(task, resources.get(task.resource_id))
            count += 1
    await db.commit()
    return {"ok": True, "updated": count}


@router.post("/batch-cancel")
async def batch_cancel_tasks(
    req: BatchTaskRequest,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    tasks, resources = await _load_tasks_with_resources(db, req.task_ids)
    count = 0
    for task in tasks:
        if task.status in ("pending", "running", "failed_retryable", "pause_requested", "paused"):
            _set_task_cancelled(task, resources.get(task.resource_id))
            count += 1
    await db.commit()
    return {"ok": True, "updated": count}


@router.post("/batch-delete")
async def batch_delete_tasks(
    req: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    if req.mode not in ("task_only", "task_and_resource"):
        raise HTTPException(status_code=400, detail="删除模式无效")

    tasks, _ = await _load_tasks_with_resources(db, req.task_ids)
    running = [task.id for task in tasks if task.status in ("running", "pause_requested", "cancel_requested")]
    if running:
        raise HTTPException(status_code=400, detail=f"运行中任务不能直接删除，请先暂停或取消: {running}")

    task_ids = [task.id for task in tasks]
    resource_ids = [task.resource_id for task in tasks]

    if req.mode == "task_and_resource" and resource_ids:
        deleted = await delete_resources_permanently(db, resource_ids)
        await db.commit()
        return {"ok": True, **deleted}

    if task_ids:
        await db.execute(delete(Task).where(Task.id.in_(task_ids)))

    await db.commit()
    return {
        "ok": True,
        "deleted_tasks": len(task_ids),
        "deleted_resources": 0,
    }
