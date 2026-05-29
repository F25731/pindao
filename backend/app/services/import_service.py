from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from typing import Set

from app.models import ImportBatch, Resource, Task, DuplicateReview
from app.utils.excel_io import read_file_stream
from app.utils.link_parser import parse_share_link, normalize_name, parse_tags
from app.utils.fuzzy_match import is_fuzzy_duplicate

DEDUP_BATCH_SIZE = 1000


async def process_import(
    db: AsyncSession,
    file_path: str,
    original_filename: str,
    user_id: int,
) -> dict:
    """
    流式导入，分批处理。支持百万级数据。
    每 2000 行为一批：解析 → 去重 → 写入 → commit。
    疑似重复检测只对前 2000 条已有资源做比对，避免 O(n^2)。
    """
    batch = ImportBatch(
        filename=original_filename,
        total_rows=0,
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
    total_rows = 0

    # 全局去重集合（内存中维护）
    seen_links: Set[str] = set()
    seen_share_keys: Set[str] = set()

    # 预加载疑似重复候选（只取最近 2000 条）
    fuzzy_candidates = await _load_fuzzy_candidates(db)

    for row_batch in read_file_stream(file_path, batch_size=2000):
        total_rows += len(row_batch)

        # 解析当前批次
        parsed = []
        batch_links = []
        batch_share_ids = []

        for name, tags, link in row_batch:
            share_id, extract_code = parse_share_link(link)
            if not share_id:
                parse_failed += 1
                continue
            valid_rows += 1
            parsed.append((name, tags, link, share_id, extract_code or ""))
            batch_links.append(link)
            batch_share_ids.append(share_id)

        # 批量查数据库去重
        existing_links = await _batch_check_links(db, batch_links)
        existing_share_keys = await _batch_check_share_keys(db, batch_share_ids)

        # 处理当前批次
        resources_to_add = []
        tasks_to_add = []
        reviews_to_add = []

        for name, tags, link, share_id, extract_code in parsed:
            # 批次内去重
            if link in seen_links:
                duplicate_skipped += 1
                continue
            share_key = f"{share_id}:{extract_code}"
            if share_key in seen_share_keys:
                duplicate_skipped += 1
                continue

            seen_links.add(link)
            seen_share_keys.add(share_key)

            # 数据库去重
            if link in existing_links:
                duplicate_skipped += 1
                continue
            if share_key in existing_share_keys:
                duplicate_skipped += 1
                continue

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
                extract_code=extract_code,
                status="待转存",
            )
            resources_to_add.append((resource, name_norm, tags_list))

        # 批量写入资源
        for resource, _, _ in resources_to_add:
            db.add(resource)
        await db.flush()

        # 疑似重复检测 + 创建任务
        for resource, name_norm, tags_list in resources_to_add:
            fuzzy_found = False
            for existing_id, existing_name_norm, existing_tags in fuzzy_candidates:
                is_dup, score, reason = is_fuzzy_duplicate(
                    name_norm, tags_list,
                    existing_name_norm, existing_tags,
                )
                if is_dup:
                    reviews_to_add.append(DuplicateReview(
                        new_resource_id=resource.id,
                        existing_resource_id=existing_id,
                        similarity_score=score,
                        match_reason=reason,
                    ))
                    resource.status = "疑似重复待审核"
                    fuzzy_found = True
                    fuzzy_flagged += 1
                    break

            if not fuzzy_found:
                tasks_to_add.append(Task(
                    resource_id=resource.id,
                    task_type="transfer",
                    status="pending",
                ))
                new_count += 1

        if tasks_to_add:
            db.add_all(tasks_to_add)
        if reviews_to_add:
            db.add_all(reviews_to_add)

        # 每批 commit 一次，避免超大事务
        await db.commit()

    # 更新批次统计
    batch.total_rows = total_rows
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
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "new_count": new_count,
        "duplicate_skipped": duplicate_skipped,
        "fuzzy_flagged": fuzzy_flagged,
        "parse_failed": parse_failed,
    }


async def _load_fuzzy_candidates(db: AsyncSession):
    result = await db.execute(
        select(Resource.id, Resource.name_normalized, Resource.tags_array).where(
            Resource.name_normalized.isnot(None),
            Resource.status.notin_(["精确重复已跳过", "人工确认跳过"]),
        ).order_by(Resource.id.desc()).limit(2000)
    )
    return [(r[0], r[1] or "", r[2] or []) for r in result.all()]


async def _batch_check_links(db: AsyncSession, links: list) -> Set[str]:
    if not links:
        return set()
    existing: Set[str] = set()
    for i in range(0, len(links), DEDUP_BATCH_SIZE):
        chunk = links[i:i + DEDUP_BATCH_SIZE]
        result = await db.execute(
            select(Resource.original_link).where(Resource.original_link.in_(chunk))
        )
        existing.update(r[0] for r in result.all())
    return existing


async def _batch_check_share_keys(db: AsyncSession, share_ids: list) -> Set[str]:
    if not share_ids:
        return set()
    existing: Set[str] = set()
    unique_ids = list(set(share_ids))
    for i in range(0, len(unique_ids), DEDUP_BATCH_SIZE):
        chunk = unique_ids[i:i + DEDUP_BATCH_SIZE]
        result = await db.execute(
            select(Resource.share_id, Resource.extract_code).where(
                Resource.share_id.in_(chunk)
            )
        )
        for r in result.all():
            existing.add(f"{r[0]}:{r[1] or ''}")
    return existing
