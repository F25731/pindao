from sqlalchemy import String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from typing import Optional

from .base import Base, TimestampMixin


class DuplicateReview(TimestampMixin, Base):
    __tablename__ = "duplicate_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    new_resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"))
    existing_resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"))
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    match_reason: Mapped[Optional[str]] = mapped_column(String(256))
    decision: Mapped[str] = mapped_column(String(32), default="pending")
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("admin_users.id"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
