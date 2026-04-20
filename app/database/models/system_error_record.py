from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class SystemErrorRecord(Base, TimestampMixin):
    __tablename__ = "system_errors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    entity_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    entity_id: Mapped[int | None] = mapped_column(
        nullable=True,
        index=True,
    )

    error_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    error_message: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )
    payload: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    is_resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"SystemErrorRecord(id={self.id}, entity_type={self.entity_type!r}, "
            f"error_type={self.error_type!r}, is_resolved={self.is_resolved})"
        )