from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.order import Order
from app.payment_core.enums.order_status import OrderStatus


@dataclass
class ExpiredOrderItem:
    order_id: int
    user_id: int
    old_status: str
    new_status: str
    expires_at: datetime
    tariff_code: str
    payment_method: str
    payment_option_id: int | None


@dataclass
class ExpireOrdersResult:
    status: str
    checked_at: datetime
    expired_count: int = 0
    expired_items: list[ExpiredOrderItem] = field(default_factory=list)
    message: str | None = None


class OrderExpirationService:
    """
    Переводит просроченные неоплаченные заказы в expired.

    Правило:
    status IN (created, waiting_payment) AND expires_at <= now
    ->
    status = expired

    Это не трогает:
    - paid orders;
    - activated orders;
    - subscriptions;
    - payments;
    - VPN metadata.
    """

    EXPIRABLE_STATUSES = (
        OrderStatus.CREATED,
        OrderStatus.WAITING_PAYMENT,
    )

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def expire_due_orders(
        self,
        now: datetime | None = None,
    ) -> ExpireOrdersResult:
        checked_at = now or datetime.now(timezone.utc)

        stmt = (
            select(Order)
            .where(
                Order.status.in_(self.EXPIRABLE_STATUSES),
                Order.expires_at <= checked_at,
            )
            .order_by(Order.expires_at.asc())
        )

        result = await self.session.execute(stmt)
        orders = list(result.scalars().all())

        if not orders:
            return ExpireOrdersResult(
                status="no_expired_orders",
                checked_at=checked_at,
                expired_count=0,
                message="No unpaid orders are expired.",
            )

        expired_items: list[ExpiredOrderItem] = []

        for order in orders:
            old_status = self._enum_to_str(order.status)

            order.status = OrderStatus.EXPIRED
            order.failure_reason = "payment_timeout"
            order.updated_at = checked_at

            expired_items.append(
                ExpiredOrderItem(
                    order_id=order.id,
                    user_id=order.user_id,
                    old_status=old_status,
                    new_status=OrderStatus.EXPIRED.value,
                    expires_at=order.expires_at,
                    tariff_code=self._enum_to_str(order.tariff_code),
                    payment_method=self._enum_to_str(order.payment_method),
                    payment_option_id=order.payment_option_id,
                )
            )

        await self.session.commit()

        return ExpireOrdersResult(
            status="expired",
            checked_at=checked_at,
            expired_count=len(expired_items),
            expired_items=expired_items,
            message="Expired unpaid orders processed.",
        )

    @staticmethod
    def _enum_to_str(value: Any) -> str:
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)