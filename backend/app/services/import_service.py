from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from datetime import datetime, timezone
from typing import List, Set, Tuple

from app.models import ImportBatch, Resource, Task, DuplicateReview
from app.utils.excel_io import read_excel
from app.utils.link_parser import parse_share_link, normalize_name, parse_tags
from app.utils.fuzzy_match import is_fuzzy_duplicate

BATCH_SIZE = 500


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

    # 批次内去重
    seen_links: Set[str] = set()
    seen_share_keys: Set[str] = set()

    # 预解析所有行
    parsed_rows: List[Tuple[str, str, str, str, str]] = []
    all_links: List[str] = []
    all_share_keys: List[Tuple[str, str]] = []

    for name, tags, link in rows:
        share_id, extract_code = parse_share_link(link)
        if not share_id:
            parse_failed += 1
            continue
        valid_rows += 1
        parsed_rows.append((name, tags, link, share_id, extract_code or ""))
        all_links.append(link)
        all_share_keys.append((share_id, extract_code or ""))

    # 批量查询数据库已有链接
    existing_links: Set[str] = set()
    for i in range(0, len(all_links), BATCH_SIZE):
        chunk = all_links[i:i + BATCH_SIZE]
        result = await db.execute(
            select(Resource.original_link).where(Resource.original_link.in_(chunk))
        )
        existing_links.update(r[0] for r in result.all())

    # 批量查询数据库已有 share_id + code
    existing_share_keys: Set[str] = set()
    unique_share_ids = list(set(sk[0] for sk in all_share_keys))
    for i in range(0, len(unique_share_ids), BATCH_SIZE):
        chunk = unique_share_ids[i:i + BATCH_SIZE]
        result = await db.execute(
            select(Resource.share_id, Resource.extract_code).where(
                Resource.share_id.in_(chunk)
            )
        )
        for r in result.all():
            existing_share_keys.add(f"{r[0]}:{r[1] or ''}")

    # 加载已有资源用于疑似重复检测（取最近的一批）
    fuzzy_candidates_result = await db.execute(
        select(Resource.id, Resource.name_normalized, Resource.tags_array).where(
            Resource.name_normalized.isnot(None),
            Resource.status.notin_(["精确重复已跳过", "人工确认跳过"]),
        ).order_by(Resource.id.desc()).limit(2000)
    )
    fuzzy_candidates = [(r[0], r[1], r[2] or []) for r in fuzzy_candidates_result.all()]

    # 处理每条资源
    resources_to_add = []
    tasks_to_add = []
    reviews_to_add = []

    for name, tags, link, share_id, extract_code in parsed_rows:
        # 批次内精确去重
        if link in seen_links:
            duplicate_skipped += 1
            continue
        share_key = f"{share_id}:{extract_code}"
        if share_key in seen_share_keys:
            duplicate_skipped += 1
            continue

        seen_links.add(link)
        seen_share_keys.add(share_key)

        # 数据库精确去重
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
        resources_to_add.append(resource)

    # 批量添加资源
    db.add_all(resources_to_add)
    await db.flush()

    # 疑似重复检测 + 创建任务
    for resource in resources_to_add:
        fuzzy_found = False

        if fuzzy_candidates:
            for existing_id, existing_name_norm, existing_tags in fuzzy_candidates:
                is_dup, score, reason = is_fuzzy_duplicate(
                    resource.name_normalized or "", resource.tags_array or [],
                    existing_name_norm or "", existing_tags,
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

    # 批量添加任务和审核记录
    if tasks_to_add:
        db.add_all(tasks_to_add)
    if reviews_to_add:
        db.add_all(reviews_to_add)

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
