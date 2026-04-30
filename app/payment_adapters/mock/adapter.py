import time
from decimal import Decimal

from app.payment_adapters.base import BasePaymentAdapter, NormalizedTransaction


class MockPaymentAdapter(BasePaymentAdapter):
    """
    Тестовый adapter для проверки polling-flow без реального блокчейна.

    Каждый запуск по умолчанию генерирует новый txid,
    чтобы тесты не попадали в старые duplicate/late события.
    """

    name = "mock"

    def __init__(
        self,
        txid: str | None = None,
        amount: Decimal = Decimal("4.00"),
        currency: str = "USDT",
        network: str = "TRC20",
        address_from: str = "mock_sender_wallet",
        address_to: str = "receiver_wallet",
        confirmations: int = 3,
    ) -> None:
        suffix = str(int(time.time() * 1000))

        self.txid = txid or f"mock_txid_{suffix}"
        self.amount = amount
        self.currency = currency
        self.network = network
        self.address_from = address_from
        self.address_to = address_to
        self.confirmations = confirmations

    async def fetch_transactions(self) -> list[NormalizedTransaction]:
        return [
            NormalizedTransaction(
                txid=self.txid,
                amount=self.amount,
                currency=self.currency,
                network=self.network,
                address_from=self.address_from,
                address_to=self.address_to,
                memo_tag=None,
                confirmations=self.confirmations,
                provider=self.name,
                raw_payload={
                    "source": "mock_adapter",
                    "txid": self.txid,
                    "amount": str(self.amount),
                    "currency": self.currency,
                    "network": self.network,
                    "address_from": self.address_from,
                    "address_to": self.address_to,
                    "confirmations": self.confirmations,
                },
            )
        ]