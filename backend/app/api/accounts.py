from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.database import get_db
from app.dependencies import get_current_user
from app.models import GuangyaAccount, AdminUser
from app.services.account_pool import refresh_account_capacity

router = APIRouter()


class AccountCreate(BaseModel):
    name: str
    access_token: str
    refresh_token: str
    device_id: Optional[str] = None
    default_parent_id: Optional[str] = ""
    priority: int = 0


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    device_id: Optional[str] = None
    default_parent_id: Optional[str] = None
    priority: Optional[int] = None
    status: Optional[str] = None


class AccountOut(BaseModel):
    id: int
    name: str
    device_id: str
    status: str
    priority: int
    last_used_at: Optional[datetime]
    error_count: int
    last_error: Optional[str]
    processed_count: int
    total_capacity_bytes: Optional[int]
    used_capacity_bytes: Optional[int]
    token_expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[AccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(GuangyaAccount).order_by(GuangyaAccount.priority.desc(), GuangyaAccount.id)
    )
    return result.scalars().all()


@router.post("/refresh-all")
async def refresh_all_accounts(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(select(GuangyaAccount).order_by(GuangyaAccount.id))
    accounts = result.scalars().all()
    refreshed = 0
    failed = 0
    for account in accounts:
        try:
            await refresh_account_capacity(db, account)
            refreshed += 1
        except Exception as exc:
            account.error_count += 1
            account.last_error = f"刷新容量失败: {str(exc)[:200]}"
            failed += 1
    await db.commit()
    return {"ok": True, "refreshed": refreshed, "failed": failed}


@router.post("", response_model=AccountOut)
async def create_account(
    req: AccountCreate,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    from app.utils.security import generate_device_id

    device_id = req.device_id or generate_device_id()
    account = GuangyaAccount(
        name=req.name,
        access_token=req.access_token,
        refresh_token=req.refresh_token,
        device_id=device_id,
        default_parent_id=req.default_parent_id or "",
        priority=req.priority,
    )
    db.add(account)
    await db.flush()
    try:
        await refresh_account_capacity(db, account)
    except Exception as exc:
        account.last_error = f"刷新容量失败: {str(exc)[:200]}"
    await db.commit()
    await db.refresh(account)
    return account


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(GuangyaAccount).where(GuangyaAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    return account


@router.post("/{account_id}/refresh", response_model=AccountOut)
async def refresh_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(GuangyaAccount).where(GuangyaAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    try:
        await refresh_account_capacity(db, account)
        account.last_error = None if account.status == "available" else account.last_error
    except Exception as exc:
        account.error_count += 1
        account.last_error = f"刷新容量失败: {str(exc)[:200]}"
        await db.commit()
        raise HTTPException(status_code=400, detail=account.last_error)
    await db.commit()
    await db.refresh(account)
    return account


@router.post("/{account_id}/enable", response_model=AccountOut)
async def enable_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(GuangyaAccount).where(GuangyaAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    account.status = "available"
    account.error_count = 0
    account.last_error = None
    await db.commit()
    await db.refresh(account)
    return account


@router.put("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: int,
    req: AccountUpdate,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(GuangyaAccount).where(GuangyaAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    await db.commit()
    await db.refresh(account)
    return account


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(GuangyaAccount).where(GuangyaAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    await db.delete(account)
    await db.commit()
    return {"ok": True}
