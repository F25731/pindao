from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from typing import Optional

from app.models import GuangyaAccount
from app.services.guangya_client import GuangyaClient


async def select_available_account(db: AsyncSession) -> Optional[GuangyaAccount]:
    """
    选择一个可用账号。
    优先级: priority 高 → error_count 低 → last_used_at 最早
    """
    result = await db.execute(
        select(GuangyaAccount)
        .where(GuangyaAccount.status == "available")
        .order_by(
            GuangyaAccount.priority.desc(),
            GuangyaAccount.error_count.asc(),
            GuangyaAccount.last_used_at.asc().nullsfirst(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


def _collect_first_number(value, keys: tuple[str, ...]) -> Optional[int]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and item is not None:
                try:
                    return int(item)
                except (TypeError, ValueError):
                    pass
            found = _collect_first_number(item, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _collect_first_number(item, keys)
            if found is not None:
                return found
    return None


async def refresh_account_capacity(db: AsyncSession, account: GuangyaAccount) -> dict:
    client = GuangyaClient(
        access_token=account.access_token,
        refresh_token=account.refresh_token,
        device_id=account.device_id,
    )
    info = await client.user_info()

    if info.get("_capacity_refresh_unsupported"):
        if account.status == "available" and (
            not account.last_error or account.last_error.startswith("刷新容量失败")
        ):
            account.last_error = None
        if client.access_token != account.access_token:
            account.access_token = client.access_token
            account.refresh_token = client.refresh_token_value
        await db.flush()
        return info

    total = _collect_first_number(
        info,
        ("totalCapacity", "total_capacity", "totalSpace", "total_space", "capacity", "quota", "total"),
    )
    used = _collect_first_number(
        info,
        ("usedCapacity", "used_capacity", "usedSpace", "used_space", "used", "usage"),
    )

    if total is not None:
        account.total_capacity_bytes = total
    if used is not None:
        account.used_capacity_bytes = used

    if total is not None and used is not None:
        if total > 0 and used >= total:
            account.status = "full"
            account.last_error = "容量不足"
        elif account.status == "full" and used < total:
            account.status = "available"
            account.last_error = None

    if client.access_token != account.access_token:
        account.access_token = client.access_token
        account.refresh_token = client.refresh_token_value

    await db.flush()
    return info


async def refresh_available_account_capacities(db: AsyncSession):
    result = await db.execute(
        select(GuangyaAccount).where(GuangyaAccount.status == "available")
    )
    accounts = result.scalars().all()
    for account in accounts:
        try:
            await refresh_account_capacity(db, account)
        except Exception as exc:
            account.error_count += 1
            account.last_error = f"刷新容量失败: {str(exc)[:200]}"
            await db.flush()


async def mark_account_used(db: AsyncSession, account: GuangyaAccount):
    account.last_used_at = datetime.now(timezone.utc)
    account.processed_count += 1
    await db.flush()


async def mark_account_error(db: AsyncSession, account: GuangyaAccount, error: str):
    account.error_count += 1
    account.last_error = error
    if account.error_count >= 5:
        account.status = "disabled"
    await db.flush()


async def mark_account_full(db: AsyncSession, account: GuangyaAccount):
    account.status = "full"
    account.last_error = "容量不足"
    await db.flush()


async def mark_account_expired(db: AsyncSession, account: GuangyaAccount):
    account.status = "expired"
    account.last_error = "登录失效"
    await db.flush()


async def mark_account_rate_limited(db: AsyncSession, account: GuangyaAccount):
    account.status = "rate_limited"
    account.last_error = "风控限制"
    await db.flush()


async def reset_account_error(db: AsyncSession, account: GuangyaAccount):
    account.error_count = 0
    account.last_error = None
    await db.flush()


async def update_account_tokens(
    db: AsyncSession,
    account: GuangyaAccount,
    access_token: str,
    refresh_token: str,
    expires_at: Optional[datetime] = None,
):
    account.access_token = access_token
    account.refresh_token = refresh_token
    account.token_expires_at = expires_at
    await db.flush()
