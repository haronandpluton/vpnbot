from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class PaymentEvent(Base, TimestampMixin):
    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    external_event_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    txid: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    payload: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    processed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    processing_status: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    payment = relationship("Payment", backref="payment_events")
    order = relationship("Order", backref="payment_events")

    def __repr__(self) -> str:
        return (
            f"PaymentEvent(id={self.id}, provider={self.provider!r}, "
            f"event_type={self.event_type!r}, txid={self.txid!r})"
        )