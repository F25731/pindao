from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os
import shutil
from secrets import token_hex

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, ImportBatch, Resource
from app.services.import_service import process_import

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


class BatchOut(BaseModel):
    id: int
    filename: str
    total_rows: int
    valid_rows: int
    new_count: int
    duplicate_skipped: int
    fuzzy_flagged: int
    parse_failed: int
    status: str
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.post("/upload")
async def upload_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 或 .xls 文件")

    safe_name = f"{token_hex(8)}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = await process_import(db, file_path, file.filename, user.id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.get("/batches", response_model=List[BatchOut])
async def list_batches(
    page: int = 0,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(ImportBatch)
        .order_by(ImportBatch.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    return result.scalars().all()


@router.get("/batches/{batch_id}", response_model=BatchOut)
async def get_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(ImportBatch).where(ImportBatch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    return batch
