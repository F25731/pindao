from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, Resource, GuangyaAccount, Task

router = APIRouter()


@router.get("/overview")
async def overview(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    resource_statuses = [
        "待转存", "转存中", "转存成功", "精确重复已跳过", "疑似重复待审核",
        "人工确认跳过", "失败待重试", "最终失败", "待推送", "推送中",
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
