from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, Resource, GuangyaAccount, Task, SystemLog

router = APIRouter()


class SystemLogOut(BaseModel):
    id: int
    level: str
    source: str
    message: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/overview")
async def overview(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    resource_statuses = [
        "待转存", "转存中", "转存暂停", "已取消", "转存成功", "精确重复已跳过",
        "人工确认跳过", "失败待重试", "最终失败", "待推送", "推送队列", "推送中",
        "已推送", "推送失败待重试", "推送最终失败",
    ]
    counts = {}
    for s in resource_statuses:
        result = await db.execute(
            select(func.count(Resource.id)).where(Resource.status == s)
        )
        counts[s] = result.scalar()

    total_result = await db.execute(select(func.count(Resource.id)))
    counts["总资源数"] = total_result.scalar()

    transferred_result = await db.execute(
        select(func.count(Resource.id)).where(
            or_(Resource.transferred_at.is_not(None), Resource.new_share_link.is_not(None))
        )
    )
    counts["转存成功"] = transferred_result.scalar()

    task_statuses = ["pending", "running", "paused", "failed_retryable", "failed_final", "success", "skipped"]
    for status in task_statuses:
        result = await db.execute(select(func.count(Task.id)).where(Task.status == status))
        counts[f"任务_{status}"] = result.scalar()
    counts["转存失败任务"] = (counts.get("任务_failed_retryable") or 0) + (counts.get("任务_failed_final") or 0)

    # 今日处理
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_result = await db.execute(
        select(func.count(Resource.id)).where(Resource.transferred_at >= today_start)
    )
    counts["今日处理"] = today_result.scalar()

    # 账号统计
    available_result = await db.execute(
        select(func.count(GuangyaAccount.id)).where(GuangyaAccount.status == "available")
    )
    counts["可用账号"] = available_result.scalar()

    total_accounts = await db.execute(select(func.count(GuangyaAccount.id)))
    counts["总账号数"] = total_accounts.scalar()

    return counts


@router.get("/daily")
async def daily_stats(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = []
    now = datetime.now(timezone.utc)

    for i in range(days - 1, -1, -1):
        day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        transferred = await db.execute(
            select(func.count(Resource.id)).where(
                Resource.transferred_at >= day_start,
                Resource.transferred_at < day_end,
            )
        )
        pushed = await db.execute(
            select(func.count(Resource.id)).where(
                Resource.pushed_at >= day_start,
                Resource.pushed_at < day_end,
            )
        )
        result.append({
            "date": day_start.strftime("%m-%d"),
            "transferred": transferred.scalar(),
            "pushed": pushed.scalar(),
        })

    return result


@router.get("/logs", response_model=list[SystemLogOut])
async def system_logs(
    limit: int = 120,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    limit = max(20, min(limit, 300))
    result = await db.execute(
        select(SystemLog)
        .order_by(SystemLog.created_at.desc(), SystemLog.id.desc())
        .limit(limit)
    )
    logs = list(reversed(result.scalars().all()))
    return logs
