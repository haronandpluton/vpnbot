from datetime import datetime

from sqlalchemy import select

from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.database.models import Order
from app.database.repositories.base import BaseRepository
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod


class OrderRepository(BaseRepository):
    async def get_by_id(self, order_id: int) -> Order | None:
        stmt = select(Order).where(Order.id == order_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_waiting_order_by_user(
        self,
        user_id: int,
    ) -> Order | None:
        stmt = select(Order).where(
            Order.user_id == user_id,
            Order.status == OrderStatus.WAITING_PAYMENT,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: int,
        tariff_code: TariffCode,
        device_limit: int,
        price_usd,
        payment_method: PaymentMethod,
        payment_option_id: int | None,
        expected_amount,
        expected_currency: CurrencyCode | None,
        expected_network: NetworkCode | None,
        destination_address: str | None,
        destination_memo_tag: str | None,
        expires_at: datetime,
        source: str = "bot",
        comment: str | None = None,
    ) -> Order:
        order = Order(
            user_id=user_id,
            status=OrderStatus.WAITING_PAYMENT,
            tariff_code=tariff_code,
            device_limit=device_limit,
            price_usd=price_usd,
            payment_method=payment_method,
            payment_option_id=payment_option_id,
            expected_amount=expected_amount,
            expected_currency=expected_currency,
            expected_network=expected_network,
            destination_address=destination_address,
            destination_memo_tag=destination_memo_tag,
            expires_at=expires_at,
            source=source,
            comment=comment,
        )
        self.session.add(order)
        await self.session.flush()
        return order

    async def mark_paid(self, order: Order, paid_at: datetime) -> Order:
        order.status = OrderStatus.PAID
        order.paid_at = paid_at
        await self.session.flush()
        return order

    async def mark_activated(self, order: Order, activated_at: datetime) -> Order:
        order.status = OrderStatus.ACTIVATED
        order.activated_at = activated_at
        await self.session.flush()
        return order

    async def mark_expired(self, order: Order) -> Order:
        order.status = OrderStatus.EXPIRED
        await self.session.flush()
        return order

    async def mark_failed(self, order: Order, failure_reason: str | None = None) -> Order:
        order.status = OrderStatus.FAILED
        order.failure_reason = failure_reason
        await self.session.flush()
        return order

    async def mark_cancelled(self, order: Order, failure_reason: str | None = None) -> Order:
        order.status = OrderStatus.CANCELLED
        order.failure_reason = failure_reason
        await self.session.flush()
        return order