from enum import StrEnum


class AppEnv(StrEnum):
    DEV = "dev"
    PROD = "prod"
    TEST = "test"


class CurrencyCode(StrEnum):
    USDT = "USDT"
    USDC = "USDC"
    BTC = "BTC"
    ETH = "ETH"
    XRP = "XRP"
    SOL = "SOL"


class NetworkCode(StrEnum):
    TRC20 = "TRC20"
    ERC20 = "ERC20"
    BEP20 = "BEP20"
    POLYGON = "POLYGON"
    SOLANA = "SOLANA"
    XRPL = "XRPL"


class TariffCode(StrEnum):
    # Legacy-коды. Оставляем для существующих заказов.
    DEVICES_1 = "devices_1"
    DEVICES_2 = "devices_2"
    DEVICES_3 = "devices_3"

    PERIOD_1_MONTH = "period_1_month"
    PERIOD_2_MONTHS = "period_2_months"
    PERIOD_3_MONTHS = "period_3_months"