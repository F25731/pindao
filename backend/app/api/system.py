from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, Resource, Task
from app.services.system_control import get_worker_concurrency, get_worker_control, set_worker_concurrency, set_worker_control

router = APIRouter()


class PauseRequest(BaseModel):
    reason: str | None = None


class ConcurrencyRequest(BaseModel):
    max_concurrent: int


@router.get("/control")
async def get_control(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    control = await get_worker_control(db)
    running = await db.scalar(select(func.count(Task.id)).where(Task.status == "running"))
    pending = await db.scalar(select(func.count(Task.id)).where(Task.status == "pending"))
    paused = await db.scalar(select(func.count(Task.id)).where(Task.status == "paused"))
    return {
        "worker_paused": bool(control.get("paused")),
        "reason": control.get("reason") or "",
        "max_concurrent": await get_worker_concurrency(db),
        "updated_at": control.get("updated_at"),
        "running_tasks": running or 0,
        "pending_tasks": pending or 0,
        "paused_tasks": paused or 0,
    }


@router.post("/pause")
async def pause_system(
    req: PauseRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    control = await set_worker_control(
        db,
        paused=True,
        reason=(req.reason if req else None) or "管理员全局暂停",
    )

    result = await db.execute(
        select(Task).where(
            Task.task_type == "transfer",
            Task.status.in_(("pending", "failed_retryable", "running", "pause_requested")),
        )
    )
    tasks = result.scalars().all()
    resource_ids = [task.resource_id for task in tasks]
    resources = {}
    if resource_ids:
        res_result = await db.execute(select(Resource).where(Resource.id.in_(resource_ids)))
        resources = {resource.id: resource for resource in res_result.scalars().all()}

    paused_now = 0
    pause_requested = 0
    for task in tasks:
        resource = resources.get(task.resource_id)
        if task.status == "running":
            checkpoint = task.checkpoint or {}
            checkpoint["pause_requested"] = True
            task.checkpoint = checkpoint
            task.status = "pause_requested"
            pause_requested += 1
        else:
            task.status = "paused"
            task.next_retry_at = None
            paused_now += 1

        task.error_message = task.error_message or "管理员全局暂停"
        if resource and resource.status in ("待转存", "转存中", "失败待重试"):
            resource.status = "转存暂停"
            resource.error_message = resource.error_message or "管理员全局暂停"

    await db.commit()
    return {
        "ok": True,
        "worker_paused": bool(control.get("paused")),
        "paused": paused_now,
        "pause_requested": pause_requested,
    }


@router.post("/resume")
async def resume_system(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    control = await set_worker_control(db, paused=False, reason="管理员恢复运行")
    await db.commit()
    return {
        "ok": True,
        "worker_paused": bool(control.get("paused")),
    }


@router.post("/concurrency")
async def update_concurrency(
    req: ConcurrencyRequest,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    value = max(1, min(int(req.max_concurrent), 10))
    control = await set_worker_concurrency(db, value)
    await db.commit()
    return {
        "ok": True,
        "max_concurrent": control.get("max_concurrent"),
        "worker_paused": bool(control.get("paused")),
    }
