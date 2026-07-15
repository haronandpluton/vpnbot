from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.config.tariffs import get_tariff
from app.database.repositories.orders import OrderRepository
from app.database.repositories.payment_options import PaymentOptionRepository
from app.database.repositories.subscriptions import SubscriptionRepository
from app.database.repositories.users import UserRepository
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.subscription_status import SubscriptionStatus


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.user_repository = UserRepository(session)
        self.order_repository = OrderRepository(session)
        self.payment_option_repository = PaymentOptionRepository(session)
        self.subscription_repository = SubscriptionRepository(session)

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language_code: str | None = None,
    ):
        user = await self.user_repository.get_by_telegram_id(telegram_id)
        if user is not None:
            await self.user_repository.update_basic_info(
                user=user,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
            )
            return user

        is_admin = telegram_id in self.settings.admin_ids

        user = await self.user_repository.create(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            is_admin=is_admin,
        )
        return user

    async def get_order_for_telegram_user(
        self,
        *,
        order_id: int,
        telegram_id: int,
    ):
        user = await self.user_repository.get_by_telegram_id(telegram_id)
        if user is None:
            return None

        order = await self.order_repository.get_by_id(order_id)
        if order is None or order.user_id != user.id:
            return None

        return order

    async def create_order(
        self,
        telegram_id: int,
        tariff_code,
        payment_option_code: str,
        target_subscription_id: int | None = None,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language_code: str | None = None,
    ):
        try:
            user = await self.get_or_create_user(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
            )

            tariff = get_tariff(tariff_code)

            await self._validate_target_subscription(
                user_id=user.id,
                target_subscription_id=target_subscription_id,
                tariff_device_limit=tariff.device_limit,
            )

            payment_option = await self.payment_option_repository.get_by_code(
                payment_option_code
            )
            if payment_option is None:
                raise ValueError(
                    f"Payment option not found in DB: {payment_option_code}"
                )

            waiting_order_kwargs = {
                "user_id": user.id,
                "tariff_code": tariff.code,
                "payment_option_id": payment_option.id,
            }
            if target_subscription_id is not None:
                waiting_order_kwargs["target_subscription_id"] = target_subscription_id

            existing_order = (
                await self.order_repository.get_active_waiting_order_by_user(
                    **waiting_order_kwargs
                )
            )
            if existing_order is not None:
                await self.session.commit()
                return existing_order

            expires_at = datetime.now(UTC) + timedelta(
                minutes=self.settings.order_ttl_minutes,
            )

            expected_amount = None

            if payment_option.payment_method == PaymentMethod.TELEGRAM_STARS:
                if tariff.stars_price is None or tariff.stars_price <= 0:
                    raise ValueError(
                        f"Telegram Stars price is not configured for {tariff.code.value}"
                    )

                expected_amount = Decimal(tariff.stars_price)

            create_order_kwargs = {
                "user_id": user.id,
                "tariff_code": tariff.code,
                "device_limit": tariff.device_limit,
                "duration_days": tariff.duration_days,
                "price_usd": tariff.price_usd,
                "payment_method": payment_option.payment_method,
                "payment_option_id": payment_option.id,
                "expected_amount": expected_amount,
                "expected_currency": payment_option.currency,
                "expected_network": payment_option.network,
                "destination_address": None,
                "destination_memo_tag": None,
                "expires_at": expires_at,
                "source": "bot",
                "comment": None,
            }
            if target_subscription_id is not None:
                create_order_kwargs["target_subscription_id"] = target_subscription_id

            order = await self.order_repository.create(**create_order_kwargs)

            await self.session.commit()
            return order

        except Exception:
            await self.session.rollback()
            raise

    async def _validate_target_subscription(
        self,
        *,
        user_id: int,
        target_subscription_id: int | None,
        tariff_device_limit: int,
    ) -> None:
        if target_subscription_id is None:
            return

        if target_subscription_id <= 0:
            raise ValueError(f"Target subscription not found: {target_subscription_id}")

        subscription = await self.subscription_repository.get_by_id(
            target_subscription_id
        )

        if subscription is None or subscription.user_id != user_id:
            raise ValueError(f"Target subscription not found: {target_subscription_id}")

        if subscription.status not in {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.EXPIRED,
        }:
            raise ValueError(
                "Target subscription is not renewable. "
                f"subscription_id={subscription.id}, "
                f"status={subscription.status.value}"
            )

        if subscription.device_limit != tariff_device_limit:
            raise ValueError(
                "Target subscription device limit does not match tariff. "
                f"subscription_id={subscription.id}, "
                f"subscription_device_limit={subscription.device_limit}, "
                f"tariff_device_limit={tariff_device_limit}"
            )

    async def expire_order(self, order_id: int):
        try:
            order = await self.order_repository.get_by_id(order_id)
            if order is None:
                return None

            if order.status.value == "waiting_payment":
                await self.order_repository.mark_expired(order)
                await self.session.commit()
                return order

            await self.session.commit()
            return order

        except Exception:
            await self.session.rollback()
            raise
