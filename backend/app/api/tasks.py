from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, GuangyaAccount, Resource, Task
from app.services.delete_service import delete_resources_permanently
from app.services.system_control import set_worker_control

router = APIRouter()
QUERY_CHUNK_SIZE = 1000
RETRY_ONLY_STATUSES = {"failed_retryable", "failed_final", "skipped"}
STARTABLE_STATUSES = {"pending", "paused", "pause_requested"}

ACCOUNT_BLOCKED_KEYWORDS = (
    "没有可用账号",
    "无可用账号",
    "可用账号",
    "账号容量",
    "容量不足",
    "空间不足",
    "账号已满",
    "分配的账号不可用",
    "切换账号",
)


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
    paused_from_status: Optional[str] = None

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    items: List[TaskOut]
    total: int


class FailedTaskOut(TaskOut):
    resource_name: Optional[str] = None
    resource_status: Optional[str] = None
    original_link: Optional[str] = None
    new_share_link: Optional[str] = None
    resource_error_message: Optional[str] = None


class FailedTaskListResponse(BaseModel):
    items: List[FailedTaskOut]
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
    tasks = result.scalars().all()
    items = [_task_out(task) for task in tasks]
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


@router.get("/failed", response_model=FailedTaskListResponse)
async def list_failed_tasks(
    page: int = 0,
    page_size: int = 20,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    failed_statuses = ("failed_retryable", "failed_final")
    query = (
        select(Task, Resource)
        .join(Resource, Task.resource_id == Resource.id, isouter=True)
        .where(Task.status.in_(failed_statuses))
    )
    count_query = select(func.count(Task.id)).where(Task.status.in_(failed_statuses))

    if search:
        keyword = f"%{search.strip()}%"
        search_filter = (
            Resource.name.ilike(keyword)
            | Resource.original_link.ilike(keyword)
            | Resource.new_share_link.ilike(keyword)
            | Task.error_message.ilike(keyword)
            | Resource.error_message.ilike(keyword)
        )
        query = query.where(search_filter)
        count_query = (
            select(func.count(Task.id))
            .join(Resource, Task.resource_id == Resource.id, isouter=True)
            .where(Task.status.in_(failed_statuses), search_filter)
        )

    total = await db.scalar(count_query)
    result = await db.execute(
        query.order_by(Task.updated_at.desc(), Task.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )

    items = []
    for task, resource in result.all():
        data = TaskOut.model_validate(task).model_dump()
        data.update({
            "resource_name": resource.name if resource else None,
            "resource_status": resource.status if resource else None,
            "original_link": resource.original_link if resource else None,
            "new_share_link": resource.new_share_link if resource else None,
            "resource_error_message": resource.error_message if resource else None,
        })
        items.append(FailedTaskOut(**data))

    return FailedTaskListResponse(items=items, total=total or 0)


def _task_out(task: Task) -> TaskOut:
    data = TaskOut.model_validate(task).model_dump()
    data["paused_from_status"] = (task.checkpoint or {}).get("paused_from_status")
    return TaskOut(**data)


@router.post("/failed/retry-all")
async def retry_all_failed_tasks(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(Task, Resource)
        .join(Resource, Task.resource_id == Resource.id, isouter=True)
        .where(Task.status.in_(("failed_retryable", "failed_final")))
        .order_by(Task.created_at.asc())
    )

    updated = 0
    for task, resource in result.all():
        _set_task_retry(task, resource)
        updated += 1

    await db.commit()
    return {"ok": True, "updated": updated}


def _set_task_paused(task: Task, resource: Resource | None):
    if task.status == "running":
        checkpoint = task.checkpoint or {}
        checkpoint["paused_from_status"] = task.status
        checkpoint["pause_requested"] = True
        task.checkpoint = checkpoint
        task.status = "pause_requested"
    elif task.status in ("pending", "failed_retryable", "pause_requested", "paused"):
        checkpoint = task.checkpoint or {}
        checkpoint.setdefault("paused_from_status", task.status)
        task.checkpoint = checkpoint
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
    checkpoint.pop("paused_from_status", None)
    task.checkpoint = checkpoint
    task.status = "pending"
    task.account_id = None
    task.next_retry_at = None
    task.completed_at = None
    if task.error_message or old_status in ("failed_final", "failed_retryable", "skipped"):
        task.error_message = None
        task.error_response = None
    if resource:
        resource.status = "待转存"


def _must_use_retry(task: Task) -> bool:
    if task.status in RETRY_ONLY_STATUSES:
        return True
    if task.status in ("paused", "pause_requested"):
        checkpoint = task.checkpoint or {}
        return checkpoint.get("paused_from_status") in RETRY_ONLY_STATUSES
    return False


def _can_start_without_retry(task: Task) -> bool:
    return task.status in STARTABLE_STATUSES and not _must_use_retry(task)


def _set_task_retry(task: Task, resource: Resource | None):
    task.status = "pending"
    task.account_id = None
    task.attempt = 0
    task.error_message = None
    task.error_response = None
    task.checkpoint = None
    task.started_at = None
    task.completed_at = None
    task.next_retry_at = None
    if resource:
        resource.status = "待转存"
        resource.transfer_account_id = None
        resource.retry_count = 0
        resource.error_message = None
        resource.error_response = None


def _is_account_blocked_task(task: Task, resource: Resource | None) -> bool:
    if task.task_type != "transfer":
        return False
    if task.status not in ("paused", "failed_retryable", "failed_final"):
        return False

    parts = [
        task.error_message or "",
        str(task.error_response or ""),
        str(task.checkpoint or ""),
    ]
    if resource:
        parts.extend(
            [
                resource.status or "",
                resource.error_message or "",
                str(resource.error_response or ""),
            ]
        )
    text = " ".join(parts)
    return any(keyword in text for keyword in ACCOUNT_BLOCKED_KEYWORDS)


async def _load_tasks_with_resources(db: AsyncSession, task_ids: List[int]):
    if not task_ids:
        raise HTTPException(status_code=400, detail="请选择任务")
    tasks = []
    for chunk in _chunks(list(dict.fromkeys(task_ids)), QUERY_CHUNK_SIZE):
        result = await db.execute(select(Task).where(Task.id.in_(chunk)))
        tasks.extend(result.scalars().all())

    resource_ids = [task.resource_id for task in tasks]
    resources = {}
    for chunk in _chunks(list(dict.fromkeys(resource_ids)), QUERY_CHUNK_SIZE):
        res_result = await db.execute(select(Resource).where(Resource.id.in_(chunk)))
        resources.update({resource.id: resource for resource in res_result.scalars().all()})
    return tasks, resources


def _chunks(values: List[int], size: int):
    for i in range(0, len(values), size):
        yield values[i:i + size]


@router.post("/resume-account-blocked")
async def resume_account_blocked_tasks(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    available_accounts = await db.scalar(
        select(func.count(GuangyaAccount.id)).where(GuangyaAccount.status == "available")
    )
    if not available_accounts:
        raise HTTPException(status_code=400, detail="没有可用账号，请先新增或启用至少一个光鸭账号")

    result = await db.execute(
        select(Task, Resource)
        .join(Resource, Task.resource_id == Resource.id)
        .where(
            Task.task_type == "transfer",
            Task.status.in_(("paused", "failed_retryable")),
        )
        .order_by(Task.created_at.asc())
    )

    updated = 0
    skipped = 0
    for task, resource in result.all():
        if not _is_account_blocked_task(task, resource):
            skipped += 1
            continue
        _set_task_retry(task, resource)
        updated += 1

    await db.commit()
    return {
        "ok": True,
        "updated": updated,
        "skipped": skipped,
        "available_accounts": available_accounts,
    }


@router.post("/start-all")
async def start_all_tasks(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    await set_worker_control(db, paused=False, reason="一键全部开始")

    result = await db.execute(
        select(Task, Resource)
        .join(Resource, Task.resource_id == Resource.id, isouter=True)
        .where(
            Task.task_type == "transfer",
            Task.status.in_(tuple(STARTABLE_STATUSES)),
        )
        .order_by(Task.created_at.asc())
    )

    updated = 0
    for task, resource in result.all():
        if _can_start_without_retry(task):
            _set_task_started(task, resource)
            updated += 1

    await db.commit()
    return {"ok": True, "updated": updated, "worker_paused": False}


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
    if task.status not in ("paused", "pause_requested") or _must_use_retry(task):
        raise HTTPException(status_code=400, detail="当前状态不支持恢复，请使用重试操作")

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
        if _can_start_without_retry(task):
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

    for chunk in _chunks(task_ids, QUERY_CHUNK_SIZE):
        await db.execute(delete(Task).where(Task.id.in_(chunk)))

    await db.commit()
    return {
        "ok": True,
        "deleted_tasks": len(task_ids),
        "deleted_resources": 0,
    }
