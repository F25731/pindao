import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CONTROL_KEY = "worker_control"


async def get_worker_control(db: AsyncSession) -> dict:
    result = await db.execute(
        text("SELECT value FROM system_controls WHERE key = :key"),
        {"key": CONTROL_KEY},
    )
    value = result.scalar_one_or_none()
    if isinstance(value, dict):
        return value

    value = {"paused": False}
    await set_worker_control(db, paused=False)
    return value


async def is_worker_paused(db: AsyncSession) -> bool:
    control = await get_worker_control(db)
    return bool(control.get("paused"))


async def set_worker_control(db: AsyncSession, paused: bool, reason: str | None = None) -> dict:
    value = {
        "paused": paused,
        "reason": reason or "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
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
    return value
