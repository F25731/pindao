from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, DuplicateReview, Resource

router = APIRouter()


class DuplicateOut(BaseModel):
    id: int
    new_resource_id: int
    existing_resource_id: int
    similarity_score: float
    match_reason: Optional[str]
    decision: str
    decided_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class DuplicateDetail(BaseModel):
    id: int
    similarity_score: float
    match_reason: Optional[str]
    decision: str
    new_resource: dict
    existing_resource: dict


class DecisionRequest(BaseModel):
    decision: str  # skip / keep_both / use_new / use_existing


class BatchDecisionRequest(BaseModel):
    ids: List[int]
    decision: str


def resource_to_dict(r: Resource) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "tags": r.tags,
        "original_link": r.original_link,
        "share_id": r.share_id,
        "extract_code": r.extract_code,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("", response_model=List[DuplicateOut])
async def list_duplicates(
    page: int = 0,
    page_size: int = 20,
    status: str = "pending",
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    query = select(DuplicateReview).where(DuplicateReview.decision == status)
    result = await db.execute(
        query.order_by(DuplicateReview.similarity_score.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    return result.scalars().all()


@router.get("/stats")
async def duplicate_stats(
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    pending = await db.execute(
        select(func.count(DuplicateReview.id)).where(DuplicateReview.decision == "pending")
    )
    resolved = await db.execute(
        select(func.count(DuplicateReview.id)).where(DuplicateReview.decision != "pending")
    )
    return {"pending": pending.scalar(), "resolved": resolved.scalar()}


@router.get("/{review_id}", response_model=DuplicateDetail)
async def get_duplicate(
    review_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    result = await db.execute(
        select(DuplicateReview).where(DuplicateReview.id == review_id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="审核记录不存在")

    new_res = await db.execute(select(Resource).where(Resource.id == review.new_resource_id))
    existing_res = await db.execute(select(Resource).where(Resource.id == review.existing_resource_id))

    new_resource = new_res.scalar_one_or_none()
    existing_resource = existing_res.scalar_one_or_none()

    return DuplicateDetail(
        id=review.id,
        similarity_score=review.similarity_score,
        match_reason=review.match_reason,
        decision=review.decision,
        new_resource=resource_to_dict(new_resource) if new_resource else {},
        existing_resource=resource_to_dict(existing_resource) if existing_resource else {},
    )


@router.post("/{review_id}/decide")
async def decide_duplicate(
    review_id: int,
    req: DecisionRequest,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    if req.decision not in ("skip", "keep_both", "use_new", "use_existing"):
        raise HTTPException(status_code=400, detail="无效决策")

    result = await db.execute(
        select(DuplicateReview).where(DuplicateReview.id == review_id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="审核记录不存在")

    review.decision = req.decision
    review.decided_by = user.id
    review.decided_at = datetime.now(timezone.utc)

    # 更新资源状态
    new_res = await db.execute(select(Resource).where(Resource.id == review.new_resource_id))
    new_resource = new_res.scalar_one_or_none()

    if new_resource:
        if req.decision == "skip" or req.decision == "use_existing":
            new_resource.status = "人工确认跳过"
        elif req.decision in ("keep_both", "use_new"):
            new_resource.status = "待转存"

    await db.commit()
    return {"ok": True}


@router.post("/batch-decide")
async def batch_decide(
    req: BatchDecisionRequest,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    if req.decision not in ("skip", "keep_both", "use_new", "use_existing"):
        raise HTTPException(status_code=400, detail="无效决策")

    result = await db.execute(
        select(DuplicateReview).where(
            DuplicateReview.id.in_(req.ids),
            DuplicateReview.decision == "pending",
        )
    )
    reviews = result.scalars().all()
    count = 0

    for review in reviews:
        review.decision = req.decision
        review.decided_by = user.id
        review.decided_at = datetime.now(timezone.utc)

        new_res = await db.execute(select(Resource).where(Resource.id == review.new_resource_id))
        new_resource = new_res.scalar_one_or_none()
        if new_resource:
            if req.decision in ("skip", "use_existing"):
                new_resource.status = "人工确认跳过"
            elif req.decision in ("keep_both", "use_new"):
                new_resource.status = "待转存"
        count += 1

    await db.commit()
    return {"ok": True, "processed": count}
