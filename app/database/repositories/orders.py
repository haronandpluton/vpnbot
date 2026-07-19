from datetime import UTC, datetime

from sqlalchemy import select

from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.config.payment_options import CRYPTOBOT_PAYMENT_OPTION_CODES
from app.database.models import Order, PaymentOption
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
        tariff_code: TariffCode,
        payment_option_id: int,
        target_subscription_id: int | None = None,
    ) -> Order | None:
        now = datetime.now(UTC)

        if target_subscription_id is None:
            target_filter = Order.target_subscription_id.is_(None)
        else:
            target_filter = Order.target_subscription_id == target_subscription_id

        stmt = (
            select(Order)
            .where(
                Order.user_id == user_id,
                Order.tariff_code == tariff_code,
                Order.payment_option_id == payment_option_id,
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                target_filter,
            )
            .order_by(Order.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_cryptobot_order_ids(
        self,
        *,
        limit: int,
        after_id: int = 0,
    ) -> list[int]:
        """
        Return non-expired CryptoBot orders eligible for invoice polling.

        Only identifiers are returned so callers do not keep ORM instances
        or database transactions open while calling the external provider.
        """
        if limit <= 0:
            return []

        now = datetime.now(UTC)

        stmt = (
            select(Order.id)
            .join(
                PaymentOption,
                PaymentOption.id == Order.payment_option_id,
            )
            .where(
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                Order.id > after_id,
                PaymentOption.code.in_(CRYPTOBOT_PAYMENT_OPTION_CODES),
                Order.destination_memo_tag.is_not(None),
            )
            .order_by(Order.id.asc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        tariff_code: TariffCode,
        device_limit: int,
        duration_days: int,
        price_usd,
        payment_method: PaymentMethod,
        payment_option_id: int | None,
        expected_amount,
        expected_currency: CurrencyCode | None,
        expected_network: NetworkCode | None,
        destination_address: str | None,
        destination_memo_tag: str | None,
        expires_at: datetime,
        target_subscription_id: int | None = None,
        source: str = "bot",
        comment: str | None = None,
    ) -> Order:
        order = Order(
            user_id=user_id,
            status=OrderStatus.WAITING_PAYMENT,
            tariff_code=tariff_code,
            device_limit=device_limit,
            duration_days=duration_days,
            target_subscription_id=target_subscription_id,
            activated_subscription_id=None,
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
