from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import CurrencyCode, NetworkCode
from app.database.base import Base, TimestampMixin
from app.database.enums import (
    currency_code_enum,
    network_code_enum,
    payment_method_enum,
    payment_status_enum,
)
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.payment_status import PaymentStatus


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[PaymentStatus] = mapped_column(
        payment_status_enum,
        nullable=False,
        default=PaymentStatus.NEW,
        server_default=PaymentStatus.NEW.value,
        index=True,
    )

    payment_method: Mapped[PaymentMethod] = mapped_column(
        payment_method_enum,
        nullable=False,
        index=True,
    )
    payment_option_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_options.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    txid: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )
    provider_payment_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        nullable=False,
    )
    currency: Mapped[CurrencyCode | None] = mapped_column(
        currency_code_enum,
        nullable=True,
        index=True,
    )
    network: Mapped[NetworkCode | None] = mapped_column(
        network_code_enum,
        nullable=True,
        index=True,
    )

    address_from: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    address_to: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    memo_tag: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    confirmations: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    raw_payload: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    order = relationship("Order", backref="payments")
    user = relationship("User", backref="payments")
    payment_option = relationship("PaymentOption", backref="payments")

    def __repr__(self) -> str:
        return (
            f"Payment(id={self.id}, order_id={self.order_id}, "
            f"status={self.status!s}, txid={self.txid!r})"
        )