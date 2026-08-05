from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class AdsGramConversion(Base, TimestampMixin):
    __tablename__ = "adsgram_conversions"
    __table_args__ = (
        CheckConstraint(
            "goal_type IN (1, 2, 3)",
            name="ck_adsgram_conversions_goal_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed')",
            name="ck_adsgram_conversions_status",
        ),
        Index(
            "ix_adsgram_conversions_status_next_attempt_at",
            "status",
            "next_attempt_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    campaign_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    goal_type: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    claim_token: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_http_status: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    user = relationship("User", backref="adsgram_conversions")
    order = relationship("Order", backref="adsgram_conversions")

    def __repr__(self) -> str:
        return (
            f"AdsGramConversion(id={self.id}, user_id={self.user_id}, "
            f"goal_type={self.goal_type}, status={self.status!r})"
        )