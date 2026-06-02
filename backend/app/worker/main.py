"""
Worker 主入口 — 后台任务处理器。
负责转存任务的调度和执行。
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, engine
from app.config import settings
from app.models import Base, Task, Resource, GuangyaAccount
from app.services.import_service import process_next_import_batch
from app.services.schema_service import ensure_runtime_database
from app.services.system_control import is_worker_paused
from app.services.system_log import append_system_log
from app.worker.transfer_handler import execute_transfer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")


async def recover_interrupted_tasks():
    """启动时恢复中断的任务 (running → failed_retryable)。"""
    async with async_session() as db:
        timeout_threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.worker_task_timeout)
        result = await db.execute(
            select(Task).where(
                Task.status == "running",
                Task.started_at < timeout_threshold,
            )
        )
        tasks = result.scalars().all()
        for task in tasks:
            task.status = "failed_retryable"
            task.error_message = "任务超时，Worker 重启后恢复"
            await append_system_log(
                db,
                "warning",
                "worker",
                f"恢复超时任务: task_id={task.id}, resource_id={task.resource_id}",
            )
            logger.warning(f"恢复超时任务: task_id={task.id}, resource_id={task.resource_id}")
        if tasks:
            await db.commit()
            logger.info(f"共恢复 {len(tasks)} 个超时任务")


async def pick_next_task(db: AsyncSession) -> Task | None:
    """
    选择下一个待执行任务。
    优先级: 重试到期 > 最早创建的 pending
    """
    now = datetime.now(timezone.utc)

    # 优先选择重试到期的任务
    result = await db.execute(
        select(Task).where(
            Task.status == "failed_retryable",
            Task.next_retry_at <= now,
        ).order_by(Task.next_retry_at.asc()).limit(1)
    )
    task = result.scalar_one_or_none()
    if task:
        return task

    # 选择最早的 pending 任务
    result = await db.execute(
        select(Task).where(Task.status == "pending")
        .order_by(Task.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_running_count(db: AsyncSession) -> int:
    from sqlalchemy import func
    result = await db.execute(
        select(func.count(Task.id)).where(Task.status == "running")
    )
    return result.scalar()


async def process_task(task_id: int):
    """处理单个任务。"""
    async with async_session() as db:
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return
        if task.status not in ("pending", "failed_retryable", "running"):
            return

        res_result = await db.execute(
            select(Resource).where(Resource.id == task.resource_id)
        )
        resource = res_result.scalar_one_or_none()
        if not resource:
            task.status = "failed_final"
            task.error_message = "关联资源不存在"
            await db.commit()
            return

        await db.refresh(task)
        if task.status not in ("pending", "failed_retryable", "running"):
            return

        if task.status != "running":
            task.status = "running"
            task.started_at = datetime.now(timezone.utc)
            task.attempt += 1
            resource.status = "转存中"
            await db.commit()

        try:
            await execute_transfer(db, task, resource)
        except Exception as e:
            logger.error("任务执行异常: task_id=%s, error=%s", task_id, e)
            await db.rollback()
            # execute_transfer 内部已处理状态，这里是兜底
            async with async_session() as db2:
                result2 = await db2.execute(select(Task).where(Task.id == task_id))
                t = result2.scalar_one_or_none()
                if t and t.status == "running":
                    t.status = "failed_retryable"
                    t.error_message = f"未捕获异常: {str(e)[:500]}"
                    t.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=2)
                    r = await db2.execute(select(Resource).where(Resource.id == t.resource_id))
                    res = r.scalar_one_or_none()
                    if res:
                        res.status = "失败待重试"
                    await db2.commit()


async def worker_loop():
    """Worker 主循环。"""
    logger.info("Worker 启动")
    await recover_interrupted_tasks()

    while True:
        try:
            async with async_session() as db:
                if await is_worker_paused(db):
                    await asyncio.sleep(settings.worker_poll_interval)
                    continue

                imported = await process_next_import_batch(db, limit=500)
                if imported:
                    await append_system_log(db, "info", "import", f"导入管道处理 {imported} 行")
                    await db.commit()
                    logger.info(f"导入管道处理 {imported} 行")

                running = await get_running_count(db)
                available_slots = max(settings.worker_max_concurrent - running, 0)
                if available_slots <= 0:
                    await asyncio.sleep(settings.worker_poll_interval)
                    continue

                task_ids = []
                for _ in range(available_slots):
                    task = await pick_next_task(db)
                    if not task:
                        break
                    task.status = "running"
                    task.started_at = datetime.now(timezone.utc)
                    task.attempt += 1
                    res_result = await db.execute(
                        select(Resource).where(Resource.id == task.resource_id)
                    )
                    resource = res_result.scalar_one_or_none()
                    if resource:
                        resource.status = "转存中"
                    task_ids.append(task.id)
                    await db.flush()

                if not task_ids:
                    await asyncio.sleep(settings.worker_poll_interval)
                    continue

                await db.commit()
                async with async_session() as log_db:
                    await append_system_log(log_db, "info", "worker", f"开始处理任务: task_ids={task_ids}")
                    await log_db.commit()
                logger.info(f"开始处理任务: task_ids={task_ids}")

            # 在后台执行，允许主循环继续拾取下一个任务
            for task_id in task_ids:
                asyncio.create_task(process_task(task_id))
            await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"Worker 循环异常: {e}")
            try:
                async with async_session() as log_db:
                    await append_system_log(log_db, "error", "worker", f"Worker 循环异常: {str(e)[:500]}")
                    await log_db.commit()
            except Exception:
                pass
            await asyncio.sleep(settings.worker_poll_interval)


async def main():
    logger.info("光鸭资源转存 Worker 启动中...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_database(conn)
    async with async_session() as db:
        await append_system_log(db, "info", "worker", "光鸭资源转存 Worker 启动")
        await db.commit()
    await worker_loop()


if __name__ == "__main__":
    asyncio.run(main())
