from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, DuplicateReview, Resource, Task

router = APIRouter()


class DuplicateOut(BaseModel):
    id: int
    new_resource_id: int
    existing_resource_id: int
    new_name: Optional[str] = None
    new_tags: Optional[str] = None
    new_status: Optional[str] = None
    existing_name: Optional[str] = None
    existing_tags: Optional[str] = None
    existing_status: Optional[str] = None
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


def _build_duplicate_out(review: DuplicateReview, resources: dict[int, Resource]) -> DuplicateOut:
    new_resource = resources.get(review.new_resource_id)
    existing_resource = resources.get(review.existing_resource_id)
    return DuplicateOut(
        id=review.id,
        new_resource_id=review.new_resource_id,
        existing_resource_id=review.existing_resource_id,
        new_name=new_resource.name if new_resource else None,
        new_tags=new_resource.tags if new_resource else None,
        new_status=new_resource.status if new_resource else None,
        existing_name=existing_resource.name if existing_resource else None,
        existing_tags=existing_resource.tags if existing_resource else None,
        existing_status=existing_resource.status if existing_resource else None,
        similarity_score=review.similarity_score,
        match_reason=review.match_reason,
        decision=review.decision,
        decided_at=review.decided_at,
        created_at=review.created_at,
    )


async def _get_task_for_resource(db: AsyncSession, resource_id: int) -> Task | None:
    result = await db.execute(select(Task).where(Task.resource_id == resource_id))
    return result.scalar_one_or_none()


async def _ensure_transfer_task(db: AsyncSession, resource: Resource) -> None:
    task = await _get_task_for_resource(db, resource.id)
    if not task:
        db.add(Task(resource_id=resource.id, task_type="transfer", status="pending"))
        return

    if task.status in ("running", "pause_requested", "cancel_requested"):
        return
    task.status = "pending"
    task.account_id = None
    task.attempt = 0
    task.error_message = None
    task.error_response = None
    task.checkpoint = None
    task.started_at = None
    task.completed_at = None
    task.next_retry_at = None


async def _skip_transfer_task(db: AsyncSession, resource: Resource) -> None:
    task = await _get_task_for_resource(db, resource.id)
    if not task:
        return
    if task.status in ("running", "pause_requested"):
        checkpoint = task.checkpoint or {}
        checkpoint["cancel_requested"] = True
        task.checkpoint = checkpoint
        task.status = "cancel_requested"
        return
    task.status = "skipped"
    task.completed_at = datetime.now(timezone.utc)
    task.error_message = "重复审核已选择跳过当前资源"
    task.next_retry_at = None


async def _apply_duplicate_decision(
    db: AsyncSession,
    review: DuplicateReview,
    decision: str,
    user_id: int,
) -> bool:
    if review.decision != "pending":
        return False

    review.decision = decision
    review.decided_by = user_id
    review.decided_at = datetime.now(timezone.utc)

    new_res = await db.execute(select(Resource).where(Resource.id == review.new_resource_id))
    new_resource = new_res.scalar_one_or_none()
    if not new_resource:
        return True

    if decision in ("skip", "use_existing"):
        new_resource.status = "人工确认跳过"
        new_resource.duplicate_of_id = review.existing_resource_id
        await _skip_transfer_task(db, new_resource)
    elif decision in ("keep_both", "use_new"):
        new_resource.status = "待转存"
        new_resource.duplicate_of_id = None
        new_resource.error_message = None
        new_resource.error_response = None
        await _ensure_transfer_task(db, new_resource)
    return True


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
    reviews = result.scalars().all()
    resource_ids = {
        resource_id
        for review in reviews
        for resource_id in (review.new_resource_id, review.existing_resource_id)
    }
    resources: dict[int, Resource] = {}
    if resource_ids:
        res_result = await db.execute(select(Resource).where(Resource.id.in_(resource_ids)))
        resources = {resource.id: resource for resource in res_result.scalars().all()}
    return [_build_duplicate_out(review, resources) for review in reviews]


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

    if not await _apply_duplicate_decision(db, review, req.decision, user.id):
        raise HTTPException(status_code=400, detail="该审核记录已处理")

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
        if await _apply_duplicate_decision(db, review, req.decision, user.id):
            count += 1

    await db.commit()
    return {"ok": True, "processed": count}
