import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

CONTROL_KEY = "worker_control"


async def get_worker_control(db: AsyncSession) -> dict:
    result = await db.execute(
        text("SELECT value FROM system_controls WHERE key = :key"),
        {"key": CONTROL_KEY},
    )
    value = result.scalar_one_or_none()
    if isinstance(value, dict):
        value.setdefault("paused", False)
        value.setdefault("max_concurrent", settings.worker_max_concurrent)
        return value

    value = {"paused": False, "max_concurrent": settings.worker_max_concurrent}
    await _save_worker_control(db, value)
    return value


async def is_worker_paused(db: AsyncSession) -> bool:
    control = await get_worker_control(db)
    return bool(control.get("paused"))


async def get_worker_concurrency(db: AsyncSession) -> int:
    control = await get_worker_control(db)
    try:
        value = int(control.get("max_concurrent") or settings.worker_max_concurrent)
    except (TypeError, ValueError):
        value = settings.worker_max_concurrent
    return max(1, min(value, 10))


async def set_worker_control(db: AsyncSession, paused: bool, reason: str | None = None) -> dict:
    current = await get_worker_control(db)
    value = {
        "paused": paused,
        "reason": reason or "",
        "max_concurrent": get_control_concurrency(current),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _save_worker_control(db, value)
    return value


async def set_worker_concurrency(db: AsyncSession, max_concurrent: int) -> dict:
    current = await get_worker_control(db)
    value = {
        **current,
        "max_concurrent": max(1, min(int(max_concurrent), 10)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _save_worker_control(db, value)
    return value


def get_control_concurrency(control: dict) -> int:
    try:
        value = int(control.get("max_concurrent") or settings.worker_max_concurrent)
    except (TypeError, ValueError):
        value = settings.worker_max_concurrent
    return max(1, min(value, 10))


async def _save_worker_control(db: AsyncSession, value: dict) -> None:
    await db.execute(
        text(
            """
            INSERT INTO system_controls (key, value, updated_at)
            VALUES (:key, CAST(:value AS jsonb), now())
            ON CONFLICT (key)
            DO UPDATE SET value = CAST(:value AS jsonb), updated_at = now()
            """
        ),
        {"key": CONTROL_KEY, "value": json.dumps(value)},
    )
