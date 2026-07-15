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
    base_days: int
    bonus_days: int
    stars_price: int | None = None

    @property
    def duration_days(self) -> int:
        return self.base_days + self.bonus_days


TARIFFS: dict[TariffCode, TariffConfig] = {
    # Legacy-тарифы нужны для чтения старых заказов.
    TariffCode.DEVICES_1: TariffConfig(
        code=TariffCode.DEVICES_1,
        title="1 device — legacy plan",
        device_limit=1,
        price_usd=Decimal("4.00"),
        base_days=30,
        bonus_days=0,
    ),
    TariffCode.DEVICES_2: TariffConfig(
        code=TariffCode.DEVICES_2,
        title="2 devices — legacy plan",
        device_limit=2,
        price_usd=Decimal("7.00"),
        base_days=30,
        bonus_days=0,
    ),
    TariffCode.DEVICES_3: TariffConfig(
        code=TariffCode.DEVICES_3,
        title="3 devices — legacy plan",
        device_limit=3,
        price_usd=Decimal("10.00"),
        base_days=30,
        bonus_days=0,
    ),

    # Актуальные тарифы. Каждый создаёт подписку на одно устройство.
    TariffCode.PERIOD_1_MONTH: TariffConfig(
        code=TariffCode.PERIOD_1_MONTH,
        title="33 days (30 days + 3 days 🎁)",
        device_limit=1,
        price_usd=Decimal("4.00"),
        base_days=30,
        bonus_days=3,
        stars_price=300,
    ),
    TariffCode.PERIOD_2_MONTHS: TariffConfig(
        code=TariffCode.PERIOD_2_MONTHS,
        title="66 days (60 days + 6 days 🎁)",
        device_limit=1,
        price_usd=Decimal("7.50"),
        base_days=60,
        bonus_days=6,
        stars_price=600,
    ),
    TariffCode.PERIOD_3_MONTHS: TariffConfig(
        code=TariffCode.PERIOD_3_MONTHS,
        title="99 days (90 days + 9 days 🎁)",
        device_limit=1,
        price_usd=Decimal("11.00"),
        base_days=90,
        bonus_days=9,
        stars_price=900,
    ),
}


PURCHASABLE_TARIFF_CODES: tuple[TariffCode, ...] = (
    TariffCode.PERIOD_1_MONTH,
    TariffCode.PERIOD_2_MONTHS,
    TariffCode.PERIOD_3_MONTHS,
)


def get_tariff(code: TariffCode) -> TariffConfig:
    tariff = TARIFFS.get(code)

    if tariff is None:
        raise ValueError(
            f"Unsupported tariff code: {code}"
        )

    return tariff


def get_purchasable_tariffs() -> tuple[TariffConfig, ...]:
    return tuple(
        TARIFFS[code]
        for code in PURCHASABLE_TARIFF_CODES
    )