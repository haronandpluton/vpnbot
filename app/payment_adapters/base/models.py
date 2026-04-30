from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class NormalizedTransaction:
    """
    Унифицированная модель транзакции.

    Любой adapter (TRON / EVM / XRP / Volet / etc)
    обязан привести данные к этому формату.

    Это критично для:
    - масштабирования
    - независимости payment_core от источника данных
    """

    # Уникальный идентификатор транзакции в сети
    txid: str

    # Сумма перевода
    amount: Decimal

    # Валюта (например: USDT, XRP, SOL)
    currency: str

    # Сеть (например: TRC20, ERC20, XRP)
    network: str

    # Отправитель
    address_from: str | None = None

    # Получатель (наш адрес)
    address_to: str | None = None

    # Memo / Tag (для XRP, etc)
    memo_tag: str | None = None

    # Количество подтверждений
    confirmations: int | None = None

    # Провайдер (volet / tron / etc)
    provider: str | None = None

    # Сырой payload (для логов / дебага)
    raw_payload: dict[str, Any] | None = None

    def __repr__(self) -> str:
        return (
            f"NormalizedTransaction("
            f"txid={self.txid!r}, "
            f"amount={self.amount}, "
            f"currency={self.currency}, "
            f"network={self.network}"
            f")"
        )