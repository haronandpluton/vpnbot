from dataclasses import dataclass

from app.common.enums import CurrencyCode, NetworkCode
from app.payment_core.enums.payment_method import PaymentMethod


@dataclass(frozen=True, slots=True)
class PaymentOptionConfig:
    code: str
    payment_method: PaymentMethod
    currency: CurrencyCode | None
    network: NetworkCode | None
    display_name: str
    is_active: bool
    sort_order: int


PAYMENT_OPTIONS: dict[str, PaymentOptionConfig] = {
    "xrp_xrpl": PaymentOptionConfig(
        code="xrp_xrpl",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.XRP,
        network=NetworkCode.XRPL,
        display_name="XRP (XRP Ledger)",
        is_active=True,
        sort_order=10,
    ),
    "sol_solana": PaymentOptionConfig(
        code="sol_solana",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.SOL,
        network=NetworkCode.SOLANA,
        display_name="SOL (Solana)",
        is_active=True,
        sort_order=20,
    ),
    "usdt_trc20": PaymentOptionConfig(
        code="usdt_trc20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDT,
        network=NetworkCode.TRC20,
        display_name="USDT (TRC20)",
        is_active=True,
        sort_order=30,
    ),
    "usdt_erc20": PaymentOptionConfig(
        code="usdt_erc20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDT,
        network=NetworkCode.ERC20,
        display_name="USDT (ERC20)",
        is_active=True,
        sort_order=40,
    ),
    "usdt_bep20": PaymentOptionConfig(
        code="usdt_bep20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDT,
        network=NetworkCode.BEP20,
        display_name="USDT (BEP20)",
        is_active=True,
        sort_order=50,
    ),
    "usdc_erc20": PaymentOptionConfig(
        code="usdc_erc20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDC,
        network=NetworkCode.ERC20,
        display_name="USDC (ERC20)",
        is_active=True,
        sort_order=60,
    ),
    "usdc_solana": PaymentOptionConfig(
        code="usdc_solana",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDC,
        network=NetworkCode.SOLANA,
        display_name="USDC (Solana)",
        is_active=True,
        sort_order=70,
    ),
    "usdc_polygon": PaymentOptionConfig(
        code="usdc_polygon",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDC,
        network=NetworkCode.POLYGON,
        display_name="USDC (Polygon)",
        is_active=True,
        sort_order=80,
    ),
    "telegram_stars": PaymentOptionConfig(
        code="telegram_stars",
        payment_method=PaymentMethod.TELEGRAM_STARS,
        currency=None,
        network=None,
        display_name="Telegram Stars",
        is_active=False,
        sort_order=90,
    ),
}


def get_payment_option(code: str) -> PaymentOptionConfig:
    option = PAYMENT_OPTIONS.get(code)
    if option is None:
        raise ValueError(f"Unsupported payment option code: {code}")
    return option


def get_active_payment_options() -> list[PaymentOptionConfig]:
    return sorted(
        (option for option in PAYMENT_OPTIONS.values() if option.is_active),
        key=lambda item: item.sort_order,
    )