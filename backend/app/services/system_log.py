from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemLog


async def append_system_log(
    db: AsyncSession,
    level: str,
    source: str,
    message: str,
    details: dict | None = None,
) -> None:
    db.add(SystemLog(
        level=level[:16],
        source=source[:64],
        message=message[:1000],
        details=details,
    ))
