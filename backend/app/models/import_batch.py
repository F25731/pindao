from sqlalchemy import String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from typing import Optional

from .base import Base, TimestampMixin


class ImportBatch(TimestampMixin, Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    stored_path: Mapped[Optional[str]] = mapped_column(Text)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_skipped: Mapped[int] = mapped_column(Integer, default=0)
    fuzzy_flagged: Mapped[int] = mapped_column(Integer, default=0)
    parse_failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    imported_by: Mapped[Optional[int]] = mapped_column(ForeignKey("admin_users.id"))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RawImportRow(TimestampMixin, Base):
    __tablename__ = "raw_import_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    resource_id: Mapped[Optional[int]] = mapped_column(ForeignKey("resources.id"))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
