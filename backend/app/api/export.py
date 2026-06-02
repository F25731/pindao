from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from datetime import datetime
import os
from secrets import token_hex

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, Resource
from app.utils.excel_io import write_excel

router = APIRouter()

EXPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)


@router.post("/excel")
async def export_excel(
    batch_id: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    query = select(Resource)
    if batch_id:
        query = query.where(Resource.batch_id == batch_id)
    if status:
        query = query.where(Resource.status == status)

    result = await db.execute(query.order_by(Resource.id))
    resources = result.scalars().all()

    if not resources:
        raise HTTPException(status_code=404, detail="没有符合条件的资源")

    rows = []
    for r in resources:
        rows.append((r.name, r.tags or "", r.original_link, r.new_share_link or ""))

    filename = f"export_{token_hex(4)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = os.path.join(EXPORT_DIR, filename)
    write_excel(filepath, rows, headers=("名称", "标签", "源链接", "我的分享链接"))

    return {"filename": filename, "count": len(rows)}


@router.get("/download/{filename}")
async def download_file(
    filename: str,
    user: AdminUser = Depends(get_current_user),
):
    filename = os.path.basename(filename)
    filepath = os.path.join(EXPORT_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(filepath, filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
