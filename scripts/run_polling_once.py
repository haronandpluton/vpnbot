import asyncio

from app.database.session import SessionLocal
from app.payment_polling.loop import PaymentPollingLoop


async def main():
    async with SessionLocal() as session:
        polling = PaymentPollingLoop(session)

        print("START POLLING (ONE-SHOT)")

        results = await polling.run_once()

        print("\nPOLLING FINISHED")
        print("results_count =", len(results))


if __name__ == "__main__":
    asyncio.run(main())