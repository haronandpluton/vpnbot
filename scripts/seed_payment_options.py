import asyncio

from app.config.payment_options import PAYMENT_OPTIONS
from app.database.repositories.payment_options import PaymentOptionRepository
from app.database.session import SessionLocal


async def seed_payment_options() -> None:
    async with SessionLocal() as session:
        repository = PaymentOptionRepository(session)

        try:
            for option in PAYMENT_OPTIONS.values():
                existing = await repository.get_by_code(option.code)

                if existing is None:
                    await repository.create(
                        code=option.code,
                        payment_method=option.payment_method,
                        currency=option.currency,
                        network=option.network,
                        display_name=option.display_name,
                        is_active=option.is_active,
                        sort_order=option.sort_order,
                    )
                    print(f"Created payment option: {option.code}")
                else:
                    await repository.update_from_config(
                        payment_option=existing,
                        payment_method=option.payment_method,
                        currency=option.currency,
                        network=option.network,
                        display_name=option.display_name,
                        is_active=option.is_active,
                        sort_order=option.sort_order,
                    )
                    print(f"Updated payment option: {option.code}")

            await session.commit()
            print("Payment options seeded successfully.")

        except Exception:
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(seed_payment_options())