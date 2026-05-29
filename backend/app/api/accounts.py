from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.database import get_db
from app.dependencies import get_current_user
from app.models import GuangyaAccount, AdminUser

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
