from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, Payment, PaymentEvent, User
from app.payment_core.enums.payment_status import PaymentStatus


@dataclass
class AdminInvalidPaymentItem:
    payment_id: int
    order_id: int | None
    user_id: int | None
    telegram_id: int | None
    username: str | None
    amount: Decimal | None
    currency: str | None
    network: str | None
    txid: str | None
    reason: str | None
    event_id: int | None
    created_at: datetime | None


class AdminInvalidPaymentsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_last_invalid_payments(
        self,
        limit: int = 10,
    ) -> list[AdminInvalidPaymentItem]:
        stmt = (
            select(Payment, Order, User, PaymentEvent)
            .join(Order, Payment.order_id == Order.id, isouter=True)
            .join(User, Payment.user_id == User.id, isouter=True)
            .join(PaymentEvent, PaymentEvent.payment_id == Payment.id, isouter=True)
            .where(Payment.status == PaymentStatus.INVALID)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        items: list[AdminInvalidPaymentItem] = []

        for payment, order, user, event in rows:
            items.append(
                AdminInvalidPaymentItem(
                    payment_id=payment.id,
                    order_id=None if order is None else order.id,
                    user_id=None if user is None else user.id,
                    telegram_id=None if user is None else user.telegram_id,
                    username=None if user is None else user.username,
                    amount=payment.amount,
                    currency=self._enum_to_str(payment.currency),
                    network=self._enum_to_str(payment.network),
                    txid=payment.txid,
                    reason=None if event is None else event.error_message,
                    event_id=None if event is None else event.id,
                    created_at=payment.created_at,
                )
            )

        return items

    @staticmethod
    def _enum_to_str(value) -> str | None:
        if value is None:
            return None

        if hasattr(value, "value"):
            return value.value

        return str(value)