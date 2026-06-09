from __future__ import annotations

import base64
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ApiKey, Resource, TelegramPushRecord
from app.utils.link_parser import parse_share_link
from app.utils.security import hash_api_key
from app.utils.search_index import normalize_search_keyword

router = APIRouter()


async def _load_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    key_hash = hash_api_key(x_api_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=401, detail="无效的 API 密钥")
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="API 密钥已过期")
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return api_key


def require_api_key(required_permissions: Optional[Sequence[str]] = None):
    required = tuple(required_permissions or ())

    async def dependency(api_key: ApiKey = Depends(_load_api_key)) -> ApiKey:
        if required:
            permissions = set(api_key.permissions or [])
            missing = [permission for permission in required if permission not in permissions]
            if missing:
                raise HTTPException(
                    status_code=403,
                    detail=f"API 密钥缺少权限: {', '.join(missing)}",
                )
        return api_key

    return dependency


class PushItem(BaseModel):
    id: int
    name: str
    tags: Optional[str]
    share_link: Optional[str]
    extract_code: Optional[str]
    transferred_at: Optional[datetime]
    text: str


class CallbackRequest(BaseModel):
    resource_id: int
    status: str  # success / failed
    error_message: Optional[str] = None
    message_id: Optional[str] = None
    response_payload: Optional[dict] = None


class SearchItem(BaseModel):
    id: int
    name: str
    tags: Optional[str]
    link: str


class SearchDetail(SearchItem):
    extract_code: Optional[str] = None


class SearchResponse(BaseModel):
    items: list[SearchItem]
    next_cursor: Optional[str] = None
    has_more: bool = False


def build_push_text(resource: Resource) -> str:
    link = resource.new_share_link or resource.original_link
    return "\n".join(
        [
            f"名称：{resource.name}",
            f"标签：{resource.tags or ''}",
            f"链接：{link or ''}",
        ]
    )


def build_push_item(resource: Resource) -> PushItem:
    return PushItem(
        id=resource.id,
        name=resource.name,
        tags=resource.tags,
        share_link=resource.new_share_link,
        extract_code=resource.new_extract_code,
        transferred_at=resource.transferred_at,
        text=build_push_text(resource),
    )


def build_search_item(resource: Resource) -> SearchItem:
    return SearchItem(
        id=resource.id,
        name=resource.name,
        tags=resource.tags,
        link=resource.new_share_link or resource.original_link,
    )


def build_search_detail(resource: Resource) -> SearchDetail:
    return SearchDetail(
        id=resource.id,
        name=resource.name,
        tags=resource.tags,
        link=resource.new_share_link or resource.original_link,
        extract_code=resource.new_extract_code or resource.extract_code,
    )


def encode_cursor(created_at: datetime, resource_id: int) -> str:
    payload = {
        "created_at": created_at.isoformat(),
        "id": resource_id,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    padding = "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"])
        resource_id = int(payload["id"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at, resource_id
    except Exception as exc:
        raise HTTPException(status_code=400, detail="无效的游标参数") from exc


def build_search_conditions(keyword: str):
    raw = keyword.strip()
    normalized = normalize_search_keyword(raw)
    if not normalized:
        raise HTTPException(status_code=400, detail="检索关键词不能为空")

    conditions = [Resource.search_text.ilike(f"%{normalized}%")]

    share_id, extract_code = parse_share_link(raw)
    if share_id:
        if extract_code:
            conditions.append(and_(Resource.share_id == share_id, Resource.extract_code == extract_code))
            conditions.append(and_(Resource.new_share_id == share_id, Resource.new_extract_code == extract_code))
        else:
            conditions.append(Resource.share_id == share_id)
            conditions.append(Resource.new_share_id == share_id)

    if raw.startswith("http://") or raw.startswith("https://"):
        conditions.append(Resource.original_link == raw)
        conditions.append(Resource.new_share_link == raw)

    return or_(*conditions)


@router.get("/push/health")
async def health(api_key: ApiKey = Depends(require_api_key(["push:read"]))):
    return {"status": "ok", "key_name": api_key.name}


@router.get("/push/pending")
async def get_pending(
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key(["push:read"])),
):
    result = await db.execute(
        select(Resource)
        .where(Resource.status == "推送队列")
        .order_by(Resource.transferred_at.asc())
        .limit(limit)
    )
    resources = result.scalars().all()

    items = [build_push_item(r) for r in resources]

    total_result = await db.execute(
        select(func.count(Resource.id)).where(Resource.status == "推送队列")
    )
    total = total_result.scalar()

    return {"items": items, "total_pending": total}


@router.post("/push/lease")
async def lease_pending(
    limit: int = Query(10, ge=1, le=100),
    retry_stale_minutes: int = Query(30, ge=5, le=1440),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key(["push:read"])),
):
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=retry_stale_minutes)
    stale_result = await db.execute(
        select(Resource).where(
            Resource.status == "推送中",
            Resource.pushed_at.is_(None),
            Resource.updated_at < stale_before,
        ).limit(500)
    )
    for resource in stale_result.scalars().all():
        resource.status = "推送失败待重试"
        resource.error_message = "推送领取后超时未回调，已恢复到失败待重试，需在推送管理中重新入队"

    result = await db.execute(
        select(Resource)
        .where(Resource.status == "推送队列")
        .order_by(Resource.transferred_at.asc().nullslast(), Resource.id.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    resources = result.scalars().all()

    now = datetime.now(timezone.utc)
    items = []
    for resource in resources:
        resource.status = "推送中"
        resource.error_message = None
        payload = build_push_item(resource).model_dump(mode="json")
        db.add(
            TelegramPushRecord(
                resource_id=resource.id,
                status="running",
                push_payload=payload,
                attempt=1,
            )
        )
        items.append(payload)

    await db.commit()

    total_result = await db.execute(
        select(func.count(Resource.id)).where(Resource.status == "推送队列")
    )
    return {
        "items": items,
        "leased": len(items),
        "total_available": total_result.scalar(),
        "leased_at": now,
    }


@router.post("/push/callback")
async def push_callback(
    req: CallbackRequest,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key(["push:callback"])),
):
    result = await db.execute(
        select(Resource).where(Resource.id == req.resource_id)
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")

    if req.status == "success":
        resource.status = "已推送"
        resource.pushed_at = datetime.now(timezone.utc)
        resource.error_message = None
    elif req.status == "failed":
        resource.status = "推送失败待重试"
        resource.error_message = req.error_message
    else:
        raise HTTPException(status_code=400, detail="无效状态，需为 success 或 failed")

    record_result = await db.execute(
        select(TelegramPushRecord)
        .where(
            TelegramPushRecord.resource_id == resource.id,
            TelegramPushRecord.status == "running",
        )
        .order_by(TelegramPushRecord.created_at.desc())
        .limit(1)
    )
    record = record_result.scalar_one_or_none()
    if not record:
        record = TelegramPushRecord(resource_id=resource.id, status="pending")
        db.add(record)
    record.status = "success" if req.status == "success" else "failed"
    record.response_payload = {
        "message_id": req.message_id,
        "payload": req.response_payload,
    }
    record.error_message = req.error_message
    record.pushed_at = datetime.now(timezone.utc) if req.status == "success" else None

    await db.commit()
    return {"ok": True, "resource_id": resource.id, "new_status": resource.status}


@router.get("/search/health")
async def search_health(api_key: ApiKey = Depends(require_api_key(["search:read"]))):
    return {"status": "ok", "key_name": api_key.name}


@router.get("/search/resources", response_model=SearchResponse)
async def search_resources(
    q: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(10, ge=1, le=50),
    cursor: Optional[str] = Query(None, max_length=512),
    status: Optional[str] = Query(None, max_length=32),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key(["search:read"])),
):
    query = select(Resource)

    if status:
        query = query.where(Resource.status == status)

    query = query.where(build_search_conditions(q))

    if cursor:
        cursor_created_at, cursor_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Resource.created_at < cursor_created_at,
                and_(Resource.created_at == cursor_created_at, Resource.id < cursor_id),
            )
        )

    result = await db.execute(
        query.order_by(Resource.created_at.desc(), Resource.id.desc()).limit(limit + 1)
    )
    resources = result.scalars().all()

    has_more = len(resources) > limit
    resources = resources[:limit]

    items = [build_search_item(resource) for resource in resources]
    next_cursor = encode_cursor(resources[-1].created_at, resources[-1].id) if has_more and resources else None
    return SearchResponse(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get("/search/resources/{resource_id}", response_model=SearchDetail)
async def get_search_resource(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key(["search:read"])),
):
    result = await db.execute(select(Resource).where(Resource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")
    return build_search_detail(resource)
