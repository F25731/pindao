from sqlalchemy import String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from typing import Optional

from .base import Base, TimestampMixin


class ImportBatch(TimestampMixin, Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_skipped: Mapped[int] = mapped_column(Integer, default=0)
    fuzzy_flagged: Mapped[int] = mapped_column(Integer, default=0)
    parse_failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    imported_by: Mapped[Optional[int]] = mapped_column(ForeignKey("admin_users.id"))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
