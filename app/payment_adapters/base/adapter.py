from abc import ABC, abstractmethod

from app.payment_adapters.base.models import NormalizedTransaction


class BasePaymentAdapter(ABC):
    """
    Базовый интерфейс payment adapter.

    Любой реальный адаптер:
    - Volet
    - TRON
    - EVM
    - XRP
    - Solana

    должен возвращать транзакции в формате NormalizedTransaction.

    Adapter НЕ знает про:
    - orders
    - users
    - subscriptions
    - activation
    """

    name: str

    @abstractmethod
    async def fetch_transactions(self) -> list[NormalizedTransaction]:
        """
        Получить список новых / последних транзакций.

        Важно:
        один и тот же adapter может вернуть одну и ту же транзакцию несколько раз.
        Это нормально.

        Удаление дублей — задача payment core / service layer.
        """
        raise NotImplementedError

    async def fetch_transaction_by_txid(
        self,
        txid: str,
    ) -> NormalizedTransaction | None:
        """
        Получить конкретную транзакцию по txid.

        Для MVP метод необязательный.
        Реальные адаптеры могут переопределить его позже.
        """
        return None