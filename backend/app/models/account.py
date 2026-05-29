from sqlalchemy import String, Integer, BigInteger, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from typing import Optional

from .base import Base, TimestampMixin


class GuangyaAccount(TimestampMixin, Base):
    __tablename__ = "guangya_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    total_capacity_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    used_capacity_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    default_parent_id: Mapped[Optional[str]] = mapped_column(String(64), default="")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rate_limited_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
