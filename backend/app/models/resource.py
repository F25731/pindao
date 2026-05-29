from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from typing import Optional, List

from .base import Base, TimestampMixin


class Resource(TimestampMixin, Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("import_batches.id"))
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    name_normalized: Mapped[Optional[str]] = mapped_column(String(512))
    tags: Mapped[Optional[str]] = mapped_column(String(512))
    tags_array: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    original_link: Mapped[str] = mapped_column(Text, nullable=False)
    share_id: Mapped[Optional[str]] = mapped_column(String(128))
    extract_code: Mapped[Optional[str]] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="待转存")

    transfer_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("guangya_accounts.id"))
    transferred_file_id: Mapped[Optional[str]] = mapped_column(String(128))
    new_share_id: Mapped[Optional[str]] = mapped_column(String(128))
    new_extract_code: Mapped[Optional[str]] = mapped_column(String(64))
    new_share_link: Mapped[Optional[str]] = mapped_column(Text)

    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_response: Mapped[Optional[dict]] = mapped_column(JSONB)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(ForeignKey("resources.id"))

    transferred_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    pushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_resources_share_id", "share_id"),
        Index("idx_resources_status", "status"),
        Index("idx_resources_batch_id", "batch_id"),
        Index("idx_resources_original_link", "original_link"),
        Index("idx_resources_name_normalized", "name_normalized"),
    )
