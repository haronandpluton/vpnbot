from sqlalchemy import select

from app.database.models import PaymentOption
from app.database.repositories.base import BaseRepository
from app.payment_core.enums.payment_method import PaymentMethod


class PaymentOptionRepository(BaseRepository):
    async def get_by_id(self, payment_option_id: int) -> PaymentOption | None:
        stmt = select(PaymentOption).where(PaymentOption.id == payment_option_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> PaymentOption | None:
        stmt = select(PaymentOption).where(PaymentOption.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active(self) -> list[PaymentOption]:
        stmt = (
            select(PaymentOption)
            .where(PaymentOption.is_active == True)
            .order_by(PaymentOption.sort_order.asc(), PaymentOption.id.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        code: str,
        payment_method: PaymentMethod,
        currency,
        network,
        display_name: str,
        is_active: bool,
        sort_order: int,
    ) -> PaymentOption:
        payment_option = PaymentOption(
            code=code,
            payment_method=payment_method,
            currency=currency,
            network=network,
            display_name=display_name,
            is_active=is_active,
            sort_order=sort_order,
        )
        self.session.add(payment_option)
        await self.session.flush()
        return payment_option

    async def update_from_config(
        self,
        payment_option: PaymentOption,
        payment_method: PaymentMethod,
        currency,
        network,
        display_name: str,
        is_active: bool,
        sort_order: int,
    ) -> PaymentOption:
        payment_option.payment_method = payment_method
        payment_option.currency = currency
        payment_option.network = network
        payment_option.display_name = display_name
        payment_option.is_active = is_active
        payment_option.sort_order = sort_order
        await self.session.flush()
        return payment_option