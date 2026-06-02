from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Iterable, Set

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ImportBatch, RawImportRow, Resource, Task
from app.utils.excel_io import read_file_raw_stream
from app.utils.link_parser import normalize_name, parse_share_link, parse_tags

RAW_LOAD_BATCH_SIZE = 2000
PROCESS_BATCH_SIZE = 500
DEDUP_BATCH_SIZE = 500


async def enqueue_import(
    db: AsyncSession,
    file_path: str,
    original_filename: str,
    user_id: int,
) -> dict:
    batch = ImportBatch(
        filename=original_filename,
        stored_path=file_path,
        total_rows=0,
        processed_rows=0,
        status="queued_raw",
        imported_by=user_id,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "message": "文件已保存，正在后台分批导入",
    }


async def load_raw_import_rows(db: AsyncSession, batch: ImportBatch) -> int:
    if not batch.stored_path or not os.path.exists(batch.stored_path):
        batch.status = "failed"
        batch.error_message = "导入文件不存在，无法读取原始行"
        await db.commit()
        return 0

    loaded_until = await db.scalar(
        select(func.max(RawImportRow.row_number)).where(RawImportRow.batch_id == batch.id)
    )
    loaded_until = int(loaded_until or 1)
    inserted = 0
    batch.status = "raw_loading"
    await db.commit()

    try:
        for raw_batch in read_file_raw_stream(batch.stored_path, batch_size=RAW_LOAD_BATCH_SIZE):
            rows = []
            for raw in raw_batch:
                row_number = int(raw["row_number"])
                if row_number <= loaded_until:
                    continue
                rows.append({
                    "batch_id": batch.id,
                    "row_number": row_number,
                    "raw_data": raw,
                    "row_hash": _row_hash(raw),
                    "status": "pending",
                })
            if not rows:
                continue
            await db.execute(insert(RawImportRow), rows)
            inserted += len(rows)
            batch.total_rows += len(rows)
            await db.commit()

        batch.status = "queued"
        batch.error_message = None
        await db.commit()
        _remove_loaded_file(batch.stored_path)
        return inserted
    except Exception as exc:
        batch.status = "failed"
        batch.error_message = f"读取原始行失败: {str(exc)[:500]}"
        await db.commit()
        return inserted


async def process_import_rows(db: AsyncSession, batch: ImportBatch, limit: int = PROCESS_BATCH_SIZE) -> int:
    batch.status = "processing"
    result = await db.execute(
        select(RawImportRow)
        .where(RawImportRow.batch_id == batch.id, RawImportRow.status == "pending")
        .order_by(RawImportRow.row_number.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    raw_rows = result.scalars().all()
    if not raw_rows:
        remaining = await db.scalar(
            select(func.count(RawImportRow.id)).where(
                RawImportRow.batch_id == batch.id,
                RawImportRow.status == "pending",
            )
        )
        if not remaining:
            batch.status = "completed"
            batch.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return 0

    parsed_rows = []
    batch_links = []
    batch_share_ids = []
    seen_links_in_chunk: Set[str] = set()
    seen_share_keys_in_chunk: Set[str] = set()

    for raw_row in raw_rows:
        raw_data = raw_row.raw_data or {}
        name = str(raw_data.get("name") or "").strip()
        tags = str(raw_data.get("tags") or "").strip()
        link = str(raw_data.get("link") or "").strip()
        share_id, extract_code = parse_share_link(link)
        if not name or not link or not share_id:
            raw_row.status = "parse_failed"
            raw_row.error_message = "名称或链接为空，或光鸭分享链接无法解析"
            batch.parse_failed += 1
            batch.processed_rows += 1
            continue

        parsed_rows.append((raw_row, name, tags, link, share_id, extract_code or ""))
        batch_links.append(link)
        batch_share_ids.append(share_id)

    existing_links = await _batch_check_links(db, batch_links)
    existing_share_keys = await _batch_check_share_keys(db, batch_share_ids)
    resources_to_add = []
    resource_context = []
    for raw_row, name, tags, link, share_id, extract_code in parsed_rows:
        share_key = f"{share_id}:{extract_code}"
        if link in seen_links_in_chunk or share_key in seen_share_keys_in_chunk:
            _mark_duplicate(batch, raw_row, "本处理批次内重复")
            continue
        seen_links_in_chunk.add(link)
        seen_share_keys_in_chunk.add(share_key)

        if link in existing_links or share_key in existing_share_keys:
            _mark_duplicate(batch, raw_row, "数据库中已存在相同源链接或分享ID")
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
        resource_context.append((raw_row, resource))

    for resource in resources_to_add:
        db.add(resource)
    if resources_to_add:
        await db.flush()

    tasks_to_add = []
    for raw_row, resource in resource_context:
        tasks_to_add.append(Task(
            resource_id=resource.id,
            task_type="transfer",
            status="pending",
        ))
        raw_row.status = "imported"
        raw_row.resource_id = resource.id
        batch.new_count += 1
        batch.valid_rows += 1
        batch.processed_rows += 1

    if tasks_to_add:
        db.add_all(tasks_to_add)

    await db.commit()
    return len(raw_rows)


async def process_next_import_batch(db: AsyncSession, limit: int = PROCESS_BATCH_SIZE) -> int:
    raw_batch = await db.scalar(
        select(ImportBatch)
        .where(ImportBatch.status.in_(("queued_raw", "raw_loading")))
        .order_by(ImportBatch.id.asc())
        .limit(1)
    )
    if raw_batch:
        return await load_raw_import_rows(db, raw_batch)

    batch = await db.scalar(
        select(ImportBatch)
        .where(ImportBatch.status.in_(("queued", "processing")))
        .order_by(ImportBatch.id.asc())
        .limit(1)
    )
    if not batch:
        return 0
    return await process_import_rows(db, batch, limit=limit)


def _row_hash(raw: dict) -> str:
    name = str(raw.get("name") or "").strip()
    tags = str(raw.get("tags") or "").strip()
    link = str(raw.get("link") or "").strip()
    return hashlib.sha256(f"{name}\0{tags}\0{link}".encode("utf-8")).hexdigest()


def _mark_duplicate(batch: ImportBatch, row: RawImportRow, reason: str) -> None:
    row.status = "duplicate"
    row.error_message = reason
    batch.duplicate_skipped += 1
    batch.valid_rows += 1
    batch.processed_rows += 1


async def _batch_check_links(db: AsyncSession, links: Iterable[str]) -> Set[str]:
    unique_links = list({link for link in links if link})
    existing: Set[str] = set()
    for i in range(0, len(unique_links), DEDUP_BATCH_SIZE):
        chunk = unique_links[i:i + DEDUP_BATCH_SIZE]
        result = await db.execute(
            select(Resource.original_link).where(Resource.original_link.in_(chunk))
        )
        existing.update(r[0] for r in result.all())
    return existing


async def _batch_check_share_keys(db: AsyncSession, share_ids: Iterable[str]) -> Set[str]:
    unique_ids = list({share_id for share_id in share_ids if share_id})
    existing: Set[str] = set()
    for i in range(0, len(unique_ids), DEDUP_BATCH_SIZE):
        chunk = unique_ids[i:i + DEDUP_BATCH_SIZE]
        result = await db.execute(
            select(Resource.share_id, Resource.extract_code).where(
                Resource.share_id.in_(chunk)
            )
        )
        for row in result.all():
            existing.add(f"{row[0]}:{row[1] or ''}")
    return existing


def _remove_loaded_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
