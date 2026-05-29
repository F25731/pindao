from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from typing import Optional

from app.models import GuangyaAccount


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
