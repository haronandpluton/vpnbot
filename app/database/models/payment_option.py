from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import CurrencyCode, NetworkCode
from app.database.base import Base, TimestampMixin
from app.database.enums import (
    currency_code_enum,
    network_code_enum,
    payment_method_enum,
)
from app.payment_core.enums.payment_method import PaymentMethod


class PaymentOption(Base, TimestampMixin):
    __tablename__ = "payment_options"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(
        payment_method_enum,
        nullable=False,
        index=True,
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
    display_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    def __repr__(self) -> str:
        return (
            f"PaymentOption(id={self.id}, code={self.code!r}, "
            f"payment_method={self.payment_method!s})"
        )