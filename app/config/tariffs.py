from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.common.enums import TariffCode


@dataclass(frozen=True, slots=True)
class TariffConfig:
    code: TariffCode
    title: str
    device_limit: int
    price_usd: Decimal
    duration_days: int


TARIFFS: dict[TariffCode, TariffConfig] = {
    TariffCode.DEVICES_1: TariffConfig(
        code=TariffCode.DEVICES_1,
        title="1 устройство",
        device_limit=1,
        price_usd=Decimal("4.00"),
        duration_days=30,
    ),
    TariffCode.DEVICES_2: TariffConfig(
        code=TariffCode.DEVICES_2,
        title="2 устройства",
        device_limit=2,
        price_usd=Decimal("7.00"),
        duration_days=30,
    ),
    TariffCode.DEVICES_3: TariffConfig(
        code=TariffCode.DEVICES_3,
        title="3 устройства",
        device_limit=3,
        price_usd=Decimal("10.00"),
        duration_days=30,
    ),
}


def get_tariff(code: TariffCode) -> TariffConfig:
    tariff = TARIFFS.get(code)
    if tariff is None:
        raise ValueError(f"Unsupported tariff code: {code}")
    return tariff