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
                    || jsonb_build_object(
                        'paused_from_status', status,
                        'pause_requested', true,
                        'global_pause', true
                    ),
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
            SET checkpoint = COALESCE(checkpoint, '{}'::jsonb)
                    || CASE
                        WHEN COALESCE(checkpoint, '{}'::jsonb) ? 'paused_from_status'
                        THEN '{}'::jsonb
                        ELSE jsonb_build_object('paused_from_status', status)
                    END
                    || jsonb_build_object('global_pause', true),
                status = 'paused',
                next_retry_at = NULL,
                error_message = COALESCE(error_message, :reason),
                updated_at = now()
            WHERE task_type = 'transfer'
              AND status IN ('pending', 'failed_retryable')
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
    previous_control = await get_worker_control(db)
    pause_reason = previous_control.get("reason") or "\u7ba1\u7406\u5458\u5168\u5c40\u6682\u505c"
    control = await set_worker_control(db, paused=False, reason="\u7ba1\u7406\u5458\u6062\u590d\u8fd0\u884c")

    result = await db.execute(
        text(
            """
            WITH candidates AS (
                SELECT
                    id,
                    resource_id,
                    status AS current_status,
                    checkpoint->>'paused_from_status' AS previous_status
                FROM tasks
                WHERE task_type = 'transfer'
                  AND status IN ('paused', 'pause_requested')
                  AND COALESCE(checkpoint, '{}'::jsonb) ? 'paused_from_status'
                  AND checkpoint->>'paused_from_status' IN ('pending', 'failed_retryable', 'running', 'pause_requested')
            ),
            updated_tasks AS (
                UPDATE tasks AS t
                SET status = CASE
                        WHEN c.previous_status = 'failed_retryable' THEN 'failed_retryable'
                        WHEN c.previous_status = 'running' AND c.current_status = 'pause_requested' THEN 'running'
                        ELSE 'pending'
                    END,
                    next_retry_at = CASE
                        WHEN c.previous_status = 'failed_retryable' THEN now()
                        ELSE NULL
                    END,
                    started_at = CASE
                        WHEN c.previous_status = 'running' AND c.current_status = 'pause_requested' THEN t.started_at
                        ELSE NULL
                    END,
                    completed_at = NULL,
                    checkpoint = NULLIF(
                        COALESCE(t.checkpoint, '{}'::jsonb)
                            - 'paused_from_status'
                            - 'pause_requested'
                            - 'global_pause',
                        '{}'::jsonb
                    ),
                    error_message = CASE
                        WHEN (t.error_message = :pause_reason OR t.error_message = '\u7ba1\u7406\u5458\u5168\u5c40\u6682\u505c') THEN NULL
                        ELSE t.error_message
                    END,
                    updated_at = now()
                FROM candidates AS c
                WHERE t.id = c.id
                RETURNING t.id, t.resource_id, t.status AS restored_status
            ),
            updated_resources AS (
                UPDATE resources AS r
                SET status = CASE
                        WHEN u.restored_status = 'failed_retryable' THEN '\u5931\u8d25\u5f85\u91cd\u8bd5'
                        WHEN u.restored_status = 'running' THEN '\u8f6c\u5b58\u4e2d'
                        ELSE '\u5f85\u8f6c\u5b58'
                    END,
                    error_message = CASE
                        WHEN (r.error_message = :pause_reason OR r.error_message = '\u7ba1\u7406\u5458\u5168\u5c40\u6682\u505c') THEN NULL
                        ELSE r.error_message
                    END,
                    updated_at = now()
                FROM updated_tasks AS u
                WHERE r.id = u.resource_id
                RETURNING r.id
            )
            SELECT
                count(*) AS restored,
                count(*) FILTER (WHERE restored_status = 'pending') AS pending,
                count(*) FILTER (WHERE restored_status = 'failed_retryable') AS failed_retryable,
                count(*) FILTER (WHERE restored_status = 'running') AS running
            FROM updated_tasks
            """
        ),
        {"pause_reason": pause_reason},
    )
    restored = result.mappings().one()
    await db.commit()
    return {
        "ok": True,
        "worker_paused": bool(control.get("paused")),
        "restored": restored["restored"] or 0,
        "pending": restored["pending"] or 0,
        "failed_retryable": restored["failed_retryable"] or 0,
        "running": restored["running"] or 0,
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
