from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, Task
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
    reason = (req.reason if req else None) or "\u7ba1\u7406\u5458\u5168\u5c40\u6682\u505c"
    control = await set_worker_control(db, paused=True, reason=reason)

    pause_requested_result = await db.execute(
        text(
            """
            UPDATE tasks
            SET checkpoint = COALESCE(checkpoint, '{}'::jsonb)
                    || jsonb_build_object('paused_from_status', status, 'pause_requested', true),
                status = 'pause_requested',
                error_message = COALESCE(error_message, :reason),
                updated_at = now()
            WHERE task_type = 'transfer'
              AND status = 'running'
            """
        ),
        {"reason": reason},
    )

    paused_result = await db.execute(
        text(
            """
            UPDATE tasks
            SET checkpoint = CASE
                    WHEN COALESCE(checkpoint, '{}'::jsonb) ? 'paused_from_status'
                    THEN COALESCE(checkpoint, '{}'::jsonb)
                    ELSE COALESCE(checkpoint, '{}'::jsonb) || jsonb_build_object('paused_from_status', status)
                END,
                status = 'paused',
                next_retry_at = NULL,
                error_message = COALESCE(error_message, :reason),
                updated_at = now()
            WHERE task_type = 'transfer'
              AND status IN ('pending', 'failed_retryable', 'pause_requested')
            """
        ),
        {"reason": reason},
    )

    await db.execute(
        text(
            """
            UPDATE resources
            SET status = '\u8f6c\u5b58\u6682\u505c',
                error_message = COALESCE(error_message, :reason),
                updated_at = now()
            WHERE status IN ('\u5f85\u8f6c\u5b58', '\u8f6c\u5b58\u4e2d', '\u5931\u8d25\u5f85\u91cd\u8bd5')
            """
        ),
        {"reason": reason},
    )

    await db.commit()
    return {
        "ok": True,
        "worker_paused": bool(control.get("paused")),
        "paused": paused_result.rowcount or 0,
        "pause_requested": pause_requested_result.rowcount or 0,
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
