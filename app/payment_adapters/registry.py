from app.payment_adapters.base import BasePaymentAdapter
from app.payment_adapters.mock import MockPaymentAdapter


class PaymentAdapterRegistry:
    """
    Registry активных payment adapters.

    Сейчас подключен только MockPaymentAdapter.
    Позже сюда добавятся:
    - Volet
    - TRON
    - EVM
    - XRP
    - Solana
    """

    def __init__(self) -> None:
        self._adapters: list[BasePaymentAdapter] = [
            MockPaymentAdapter(),
        ]

    def get_active_adapters(self) -> list[BasePaymentAdapter]:
        return self._adapters


def get_payment_adapter_registry() -> PaymentAdapterRegistry:
    return PaymentAdapterRegistry()