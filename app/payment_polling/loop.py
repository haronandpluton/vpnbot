from sqlalchemy.ext.asyncio import AsyncSession

from app.payment_adapters.registry import get_payment_adapter_registry
from app.payment_polling.processor import PaymentPollingProcessor


class PaymentPollingLoop:
    """
    One-shot polling loop.

    Сейчас это не бесконечный daemon, а один цикл:
    - получить активные adapters;
    - забрать transactions;
    - передать их processor.

    Это проще тестировать.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.registry = get_payment_adapter_registry()
        self.processor = PaymentPollingProcessor(session)

    async def run_once(self) -> list:
        results = []

        adapters = self.registry.get_active_adapters()

        for adapter in adapters:
            try:
                transactions = await adapter.fetch_transactions()

                print("ADAPTER FETCHED:")
                print("adapter =", adapter.name)
                print("transactions_count =", len(transactions))

                adapter_results = await self.processor.process_transactions(
                    transactions
                )

                results.extend(adapter_results)

            except Exception as error:
                print("ADAPTER ERROR:")
                print("adapter =", adapter.name)
                print("error =", repr(error))

        return results