from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, Subscription, User
from app.payment_core.enums.subscription_status import SubscriptionStatus


@dataclass
class AdminActiveSubscriptionItem:
    subscription_id: int
    order_id: int | None
    user_id: int | None
    telegram_id: int | None
    username: str | None
    status: str | None
    uuid: str | None
    device_limit: int | None
    starts_at: datetime | None
    expires_at: datetime | None
    last_access_sent_at: datetime | None
    vpn_server_id: int | None
    order_status: str | None
    order_tariff_code: str | None


class AdminActiveSubscriptionsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_subscriptions(
        self,
        limit: int = 20,
    ) -> list[AdminActiveSubscriptionItem]:
        stmt = (
            select(Subscription, User, Order)
            .join(User, Subscription.user_id == User.id, isouter=True)
            .join(Order, Subscription.order_id == Order.id, isouter=True)
            .where(Subscription.status == SubscriptionStatus.ACTIVE)
            .order_by(Subscription.expires_at.asc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        items: list[AdminActiveSubscriptionItem] = []

        for subscription, user, order in rows:
            items.append(
                AdminActiveSubscriptionItem(
                    subscription_id=subscription.id,
                    order_id=subscription.order_id,
                    user_id=subscription.user_id,
                    telegram_id=None if user is None else user.telegram_id,
                    username=None if user is None else user.username,
                    status=self._enum_to_str(subscription.status),
                    uuid=subscription.uuid,
                    device_limit=subscription.device_limit,
                    starts_at=subscription.starts_at,
                    expires_at=subscription.expires_at,
                    last_access_sent_at=subscription.last_access_sent_at,
                    vpn_server_id=subscription.vpn_server_id,
                    order_status=None if order is None else self._enum_to_str(order.status),
                    order_tariff_code=None if order is None else self._enum_to_str(order.tariff_code),
                )
            )

        return items

    @staticmethod
    def _enum_to_str(value) -> str | None:
        if value is None:
            return None

        if hasattr(value, "value"):
            return str(value.value)

        return str(value)