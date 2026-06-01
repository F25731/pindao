from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DuplicateReview, ImportBatch, Resource, Task, TelegramPushRecord

RUNNING_TASK_STATUSES = {"running", "pause_requested", "cancel_requested"}


async def delete_resources_permanently(
    db: AsyncSession,
    resource_ids: Iterable[int],
) -> dict:
    ids = sorted({int(resource_id) for resource_id in resource_ids if resource_id})
    if not ids:
        return {"deleted_resources": 0, "deleted_tasks": 0, "deleted_push_records": 0, "deleted_duplicate_reviews": 0}

    running_result = await db.execute(
        select(Task.id, Task.status).where(
            Task.resource_id.in_(ids),
            Task.status.in_(RUNNING_TASK_STATUSES),
        )
    )
    running = [row[0] for row in running_result.all()]
    if running:
        raise HTTPException(status_code=400, detail=f"有运行中任务不能删除，请先暂停或取消: {running}")

    task_ids_result = await db.execute(select(Task.id).where(Task.resource_id.in_(ids)))
    task_ids = [row[0] for row in task_ids_result.all()]

    push_result = await db.execute(
        delete(TelegramPushRecord)
        .where(TelegramPushRecord.resource_id.in_(ids))
        .execution_options(synchronize_session=False)
    )
    duplicate_result = await db.execute(
        delete(DuplicateReview)
        .where(
            or_(
                DuplicateReview.new_resource_id.in_(ids),
                DuplicateReview.existing_resource_id.in_(ids),
            )
        )
        .execution_options(synchronize_session=False)
    )
    task_result = await db.execute(
        delete(Task)
        .where(Task.resource_id.in_(ids))
        .execution_options(synchronize_session=False)
    )
    resource_result = await db.execute(
        delete(Resource)
        .where(Resource.id.in_(ids))
        .execution_options(synchronize_session=False)
    )

    return {
        "deleted_resources": resource_result.rowcount or 0,
        "deleted_tasks": task_result.rowcount or len(task_ids),
        "deleted_push_records": push_result.rowcount or 0,
        "deleted_duplicate_reviews": duplicate_result.rowcount or 0,
    }


async def delete_batches_permanently(
    db: AsyncSession,
    batch_ids: Iterable[int],
) -> dict:
    ids = sorted({int(batch_id) for batch_id in batch_ids if batch_id})
    if not ids:
        return {"deleted_batches": 0, "deleted_resources": 0, "deleted_tasks": 0}

    resource_result = await db.execute(select(Resource.id).where(Resource.batch_id.in_(ids)))
    resource_ids = [row[0] for row in resource_result.all()]
    deleted = await delete_resources_permanently(db, resource_ids)

    batch_result = await db.execute(
        delete(ImportBatch)
        .where(ImportBatch.id.in_(ids))
        .execution_options(synchronize_session=False)
    )
    deleted["deleted_batches"] = batch_result.rowcount or 0
    return deleted
