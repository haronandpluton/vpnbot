import hashlib
import hmac
from dataclasses import dataclass
from typing import Mapping


class VoletSciVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class VoletSciStatusVerificationResult:
    is_valid: bool
    variant: str | None = None
    expected_hash: str | None = None
    received_hash: str | None = None


_REQUIRED_STATUS_HASH_FIELDS = (
    "ac_transfer",
    "ac_start_date",
    "ac_sci_name",
    "ac_src_wallet",
    "ac_dest_wallet",
    "ac_order_id",
    "ac_amount",
    "ac_merchant_currency",
    "ac_hash",
)


def _get_required(data: Mapping[str, str], key: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise VoletSciVerificationError(f"Missing Volet SCI field: {key}")
    return value


def calculate_volet_sci_status_hash(
    *,
    transfer: str,
    start_date: str,
    sci_name: str,
    src_wallet: str,
    dest_wallet: str,
    order_id: str,
    amount: str,
    merchant_currency: str,
    password: str,
) -> str:
    source = (
        f"{transfer}:"
        f"{start_date}:"
        f"{sci_name}:"
        f"{src_wallet}:"
        f"{dest_wallet}:"
        f"{order_id}:"
        f"{amount}:"
        f"{merchant_currency}:"
        f"{password}"
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def calculate_volet_sci_status_hash_reversed_wallets(
    *,
    transfer: str,
    start_date: str,
    sci_name: str,
    src_wallet: str,
    dest_wallet: str,
    order_id: str,
    amount: str,
    merchant_currency: str,
    password: str,
) -> str:
    # Volet SCI PDF lists src_wallet -> dest_wallet in the formula,
    # but its own example string shows dest_wallet -> src_wallet.
    # We support both variants and log which one matched.
    source = (
        f"{transfer}:"
        f"{start_date}:"
        f"{sci_name}:"
        f"{dest_wallet}:"
        f"{src_wallet}:"
        f"{order_id}:"
        f"{amount}:"
        f"{merchant_currency}:"
        f"{password}"
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def verify_volet_sci_status_hash(
    data: Mapping[str, str],
    *,
    password: str,
) -> VoletSciStatusVerificationResult:
    if not password.strip():
        raise VoletSciVerificationError("VOLET_SCI_PASSWORD is empty")

    for field in _REQUIRED_STATUS_HASH_FIELDS:
        _get_required(data, field)

    received_hash = _get_required(data, "ac_hash").lower()

    common_kwargs = {
        "transfer": _get_required(data, "ac_transfer"),
        "start_date": _get_required(data, "ac_start_date"),
        "sci_name": _get_required(data, "ac_sci_name"),
        "src_wallet": _get_required(data, "ac_src_wallet"),
        "dest_wallet": _get_required(data, "ac_dest_wallet"),
        "order_id": _get_required(data, "ac_order_id"),
        "amount": _get_required(data, "ac_amount"),
        "merchant_currency": _get_required(data, "ac_merchant_currency"),
        "password": password.strip(),
    }

    expected_hash = calculate_volet_sci_status_hash(**common_kwargs)

    if hmac.compare_digest(received_hash, expected_hash):
        return VoletSciStatusVerificationResult(
            is_valid=True,
            variant="src_dest",
            expected_hash=expected_hash,
            received_hash=received_hash,
        )

    reversed_expected_hash = calculate_volet_sci_status_hash_reversed_wallets(
        **common_kwargs,
    )

    if hmac.compare_digest(received_hash, reversed_expected_hash):
        return VoletSciStatusVerificationResult(
            is_valid=True,
            variant="dest_src",
            expected_hash=reversed_expected_hash,
            received_hash=received_hash,
        )

    return VoletSciStatusVerificationResult(
        is_valid=False,
        variant=None,
        expected_hash=expected_hash,
        received_hash=received_hash,
    )


def normalize_volet_sci_order_id(raw_order_id: str) -> int:
    value = raw_order_id.strip()

    if value.startswith("order_"):
        value = value.replace("order_", "", 1)

    try:
        return int(value)
    except ValueError as exc:
        raise VoletSciVerificationError(
            f"Invalid Volet SCI order id: {raw_order_id}",
        ) from exc


def redact_volet_sci_status_payload(data: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}

    for key, value in data.items():
        if key in {"ac_hash", "ac_buyer_email"}:
            result[key] = "***"
        else:
            result[key] = str(value)

    return result