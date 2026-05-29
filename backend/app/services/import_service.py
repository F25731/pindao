from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from datetime import datetime, timezone
from typing import List

from app.models import ImportBatch, Resource, Task, DuplicateReview
from app.utils.excel_io import read_excel
from app.utils.link_parser import parse_share_link, normalize_name, parse_tags
from app.utils.fuzzy_match import is_fuzzy_duplicate


async def process_import(
    db: AsyncSession,
    file_path: str,
    original_filename: str,
    user_id: int,
) -> dict:
    rows = read_excel(file_path)

    batch = ImportBatch(
        filename=original_filename,
        total_rows=len(rows),
        status="processing",
        imported_by=user_id,
    )
    db.add(batch)
    await db.flush()

    new_count = 0
    duplicate_skipped = 0
    fuzzy_flagged = 0
    parse_failed = 0
    valid_rows = 0

    # 批次内去重用
    seen_links = set()
    seen_share_ids = set()

    for name, tags, link in rows:
        share_id, extract_code = parse_share_link(link)

        if not share_id:
            parse_failed += 1
            continue

        valid_rows += 1

        # 批次内精确去重
        if link in seen_links:
            duplicate_skipped += 1
            continue
        share_key = f"{share_id}:{extract_code or ''}"
        if share_key in seen_share_ids:
            duplicate_skipped += 1
            continue

        seen_links.add(link)
        seen_share_ids.add(share_key)

        # 数据库精确去重: 相同链接
        existing_link = await db.execute(
            select(Resource).where(Resource.original_link == link).limit(1)
        )
        if existing_link.scalar_one_or_none():
            duplicate_skipped += 1
            continue

        # 数据库精确去重: 相同 share_id + code
        existing_share = await db.execute(
            select(Resource).where(
                Resource.share_id == share_id,
                Resource.extract_code == (extract_code or ""),
            ).limit(1)
        )
        if existing_share.scalar_one_or_none():
            duplicate_skipped += 1
            continue

        # 创建资源记录
        name_norm = normalize_name(name)
        tags_list = parse_tags(tags)

        resource = Resource(
            batch_id=batch.id,
            name=name,
            name_normalized=name_norm,
            tags=tags,
            tags_array=tags_list,
            original_link=link,
            share_id=share_id,
            extract_code=extract_code or "",
            status="待转存",
        )
        db.add(resource)
        await db.flush()

        # 疑似重复检测: 查找名称相似的已有资源
        fuzzy_found = False
        similar_results = await db.execute(
            select(Resource).where(
                Resource.id != resource.id,
                Resource.name_normalized.isnot(None),
                Resource.status.notin_(["精确重复已跳过", "人工确认跳过"]),
            ).limit(100)
        )
        existing_resources = similar_results.scalars().all()

        for existing in existing_resources:
            is_dup, score, reason = is_fuzzy_duplicate(
                name_norm, tags_list,
                existing.name_normalized or "", existing.tags_array or [],
            )
            if is_dup:
                review = DuplicateReview(
                    new_resource_id=resource.id,
                    existing_resource_id=existing.id,
                    similarity_score=score,
                    match_reason=reason,
                )
                db.add(review)
                resource.status = "疑似重复待审核"
                fuzzy_found = True
                fuzzy_flagged += 1
                break

        if not fuzzy_found:
            # 创建转存任务
            task = Task(
                resource_id=resource.id,
                task_type="transfer",
                status="pending",
            )
            db.add(task)
            new_count += 1

    # 更新批次统计
    batch.valid_rows = valid_rows
    batch.new_count = new_count
    batch.duplicate_skipped = duplicate_skipped
    batch.fuzzy_flagged = fuzzy_flagged
    batch.parse_failed = parse_failed
    batch.status = "completed"
    batch.completed_at = datetime.now(timezone.utc)

    await db.commit()

    return {
        "batch_id": batch.id,
        "total_rows": batch.total_rows,
        "valid_rows": valid_rows,
        "new_count": new_count,
        "duplicate_skipped": duplicate_skipped,
        "fuzzy_flagged": fuzzy_flagged,
        "parse_failed": parse_failed,
    }
