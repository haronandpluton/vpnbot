from enum import StrEnum


class AppEnv(StrEnum):
    DEV = "dev"
    PROD = "prod"
    TEST = "test"


class CurrencyCode(StrEnum):
    USDT = "USDT"
    USDC = "USDC"
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
    DEVICES_1 = "devices_1"
    DEVICES_2 = "devices_2"
    DEVICES_3 = "devices_3"