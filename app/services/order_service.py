from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.config.tariffs import get_tariff
from app.database.repositories.orders import OrderRepository
from app.database.repositories.payment_options import PaymentOptionRepository
from app.database.repositories.users import UserRepository


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.user_repository = UserRepository(session)
        self.order_repository = OrderRepository(session)
        self.payment_option_repository = PaymentOptionRepository(session)

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

    async def create_order(
        self,
        telegram_id: int,
        tariff_code,
        payment_option_code: str,
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

            existing_order = await self.order_repository.get_active_waiting_order_by_user(
                user_id=user.id,
            )
            if existing_order is not None:
                await self.session.commit()
                return existing_order

            tariff = get_tariff(tariff_code)

            payment_option = await self.payment_option_repository.get_by_code(
                payment_option_code
            )
            if payment_option is None:
                raise ValueError(
                    f"Payment option not found in DB: {payment_option_code}"
                )

            expires_at = datetime.now(UTC) + timedelta(
                minutes=self.settings.order_ttl_minutes,
            )

            order = await self.order_repository.create(
                user_id=user.id,
                tariff_code=tariff.code,
                device_limit=tariff.device_limit,
                price_usd=tariff.price_usd,
                payment_method=payment_option.payment_method,
                payment_option_id=payment_option.id,
                expected_amount=None,
                expected_currency=payment_option.currency,
                expected_network=payment_option.network,
                destination_address=None,
                destination_memo_tag=None,
                expires_at=expires_at,
                source="bot",
                comment=None,
            )

            await self.session.commit()
            return order

        except Exception:
            await self.session.rollback()
            raise

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