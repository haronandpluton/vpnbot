from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.database.base import Base, TimestampMixin
from app.database.enums import (
    currency_code_enum,
    network_code_enum,
    order_status_enum,
    payment_method_enum,
    tariff_code_enum,
)
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[OrderStatus] = mapped_column(
        order_status_enum,
        nullable=False,
        default=OrderStatus.CREATED,
        server_default=OrderStatus.CREATED.value,
        index=True,
    )

    tariff_code: Mapped[TariffCode] = mapped_column(
        tariff_code_enum,
        nullable=False,
        index=True,
    )
    device_limit: Mapped[int] = mapped_column(
        nullable=False,
    )

    price_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
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

    expected_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 8),
        nullable=True,
    )
    expected_currency: Mapped[CurrencyCode | None] = mapped_column(
        currency_code_enum,
        nullable=True,
        index=True,
    )
    expected_network: Mapped[NetworkCode | None] = mapped_column(
        network_code_enum,
        nullable=True,
        index=True,
    )

    destination_address: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    destination_memo_tag: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    source: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        server_default=text("'bot'"),
    )
    comment: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    failure_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    user = relationship("User", backref="orders")
    payment_option = relationship("PaymentOption", backref="orders")

    def __repr__(self) -> str:
        return (
            f"Order(id={self.id}, user_id={self.user_id}, "
            f"status={self.status!s}, tariff_code={self.tariff_code!s})"
        )