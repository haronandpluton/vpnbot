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

CRYPTOBOT_PAYMENT_OPTION_CODES: tuple[str, ...] = (
    "cryptobot_usdt",
    "cryptobot_usdc",
    "cryptobot_btc",
    "cryptobot_eth",
)

CRYPTOBOT_SUPPORTED_CURRENCIES: frozenset[CurrencyCode] = frozenset(
    {
        CurrencyCode.USDT,
        CurrencyCode.USDC,
        CurrencyCode.BTC,
        CurrencyCode.ETH,
    }
)


PAYMENT_OPTIONS: dict[str, PaymentOptionConfig] = {
    "cryptobot_usdt": PaymentOptionConfig(
        code="cryptobot_usdt",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDT,
        network=None,
        display_name="CryptoBot — USDT",
        is_active=True,
        sort_order=10,
    ),
    "cryptobot_usdc": PaymentOptionConfig(
        code="cryptobot_usdc",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDC,
        network=None,
        display_name="CryptoBot — USDC",
        is_active=True,
        sort_order=20,
    ),
    "cryptobot_btc": PaymentOptionConfig(
        code="cryptobot_btc",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.BTC,
        network=None,
        display_name="CryptoBot — BTC",
        is_active=True,
        sort_order=30,
    ),
    "cryptobot_eth": PaymentOptionConfig(
        code="cryptobot_eth",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.ETH,
        network=None,
        display_name="CryptoBot — ETH",
        is_active=True,
        sort_order=40,
    ),
    # Эти варианты оставлены в доменной модели для последующих отдельных
    # адаптеров. Пока они не должны попадать в пользовательский flow.
    "xrp_xrpl": PaymentOptionConfig(
        code="xrp_xrpl",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.XRP,
        network=NetworkCode.XRPL,
        display_name="XRP (XRP Ledger)",
        is_active=False,
        sort_order=100,
    ),
    "sol_solana": PaymentOptionConfig(
        code="sol_solana",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.SOL,
        network=NetworkCode.SOLANA,
        display_name="SOL (Solana)",
        is_active=False,
        sort_order=110,
    ),
    "usdt_trc20": PaymentOptionConfig(
        code="usdt_trc20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDT,
        network=NetworkCode.TRC20,
        display_name="USDT (TRC20)",
        is_active=False,
        sort_order=120,
    ),
    "usdt_erc20": PaymentOptionConfig(
        code="usdt_erc20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDT,
        network=NetworkCode.ERC20,
        display_name="USDT (ERC20)",
        is_active=False,
        sort_order=130,
    ),
    "usdt_bep20": PaymentOptionConfig(
        code="usdt_bep20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDT,
        network=NetworkCode.BEP20,
        display_name="USDT (BEP20)",
        is_active=False,
        sort_order=140,
    ),
    "usdc_erc20": PaymentOptionConfig(
        code="usdc_erc20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDC,
        network=NetworkCode.ERC20,
        display_name="USDC (ERC20)",
        is_active=False,
        sort_order=150,
    ),
    "usdc_solana": PaymentOptionConfig(
        code="usdc_solana",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDC,
        network=NetworkCode.SOLANA,
        display_name="USDC (Solana)",
        is_active=False,
        sort_order=160,
    ),
    "usdc_polygon": PaymentOptionConfig(
        code="usdc_polygon",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDC,
        network=NetworkCode.POLYGON,
        display_name="USDC (Polygon)",
        is_active=False,
        sort_order=170,
    ),
    "telegram_stars": PaymentOptionConfig(
        code="telegram_stars",
        payment_method=PaymentMethod.TELEGRAM_STARS,
        currency=None,
        network=None,
        display_name="Telegram Stars",
        is_active=False,
        sort_order=200,
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


def is_cryptobot_payment_option(code: str) -> bool:
    return code in CRYPTOBOT_PAYMENT_OPTION_CODES