from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models import AdminUser

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


async def ensure_admin_exists(db: AsyncSession):
    result = await db.execute(
        select(AdminUser).where(AdminUser.username == settings.admin_username)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = AdminUser(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
        )
        db.add(user)
        await db.commit()
