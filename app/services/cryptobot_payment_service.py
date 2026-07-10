from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import CurrencyCode
from app.config.payment_options import CRYPTOBOT_SUPPORTED_CURRENCIES
from app.config.settings import get_settings
from app.database.repositories.orders import OrderRepository
from app.payment_adapters.cryptobot import CryptoBotAPIError, CryptoBotClient
from app.payment_core.enums.order_status import OrderStatus
from app.services.payment_activation_service import PaymentActivationService
from app.services.payment_event_service import PaymentEventService


class CryptoBotPaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.order_repository = OrderRepository(session)

    def _client(self) -> CryptoBotClient:
        return CryptoBotClient(
            api_url=self.settings.cryptobot_api_url,
            api_token=self.settings.cryptobot_api_token,
        )

    def _invoice_id_from_order(self, order) -> int | None:
        if order.destination_memo_tag and str(order.destination_memo_tag).isdigit():
            return int(order.destination_memo_tag)

        if not order.comment:
            return None

        try:
            data = json.loads(order.comment)
        except json.JSONDecodeError:
            return None

        if data.get("provider") != "cryptobot":
            return None

        invoice_id = data.get("invoice_id")
        if invoice_id is None:
            return None

        invoice_id_raw = str(invoice_id)
        return int(invoice_id_raw) if invoice_id_raw.isdigit() else None

    @staticmethod
    def _invoice_payment_url(
        invoice: dict[str, Any],
    ) -> str | None:
        return (
            invoice.get("bot_invoice_url")
            or invoice.get("pay_url")
            or invoice.get("mini_app_invoice_url")
            or invoice.get("web_app_invoice_url")
        )

    @staticmethod
    def _decimal(value: Any, *, field_name: str) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise CryptoBotAPIError(
                f"CryptoBot invoice has invalid {field_name}: {value!r}"
            ) from exc

    @staticmethod
    def _currency_value(
        value: CurrencyCode | str | None,
    ) -> str | None:
        if value is None:
            return None

        if isinstance(value, CurrencyCode):
            return value.value

        return str(value)

    def _selected_asset(self, order) -> str:
        value = self._currency_value(order.expected_currency)
        if value is None:
            raise CryptoBotAPIError(
                f"Order #{order.id} has no expected CryptoBot currency"
            )

        try:
            currency = CurrencyCode(value)
        except ValueError as exc:
            raise CryptoBotAPIError(
                f"Order #{order.id} has unsupported currency: {value}"
            ) from exc

        if currency not in CRYPTOBOT_SUPPORTED_CURRENCIES:
            raise CryptoBotAPIError(
                f"Currency {currency.value} is not supported by CryptoBot flow"
            )

        return currency.value

    @staticmethod
    def _accepted_assets(invoice: dict[str, Any]) -> set[str]:
        raw = invoice.get("accepted_assets")
        if raw is None:
            return set()

        if isinstance(raw, str):
            return {item.strip().upper() for item in raw.split(",") if item.strip()}

        if isinstance(raw, list):
            return {str(item).strip().upper() for item in raw if str(item).strip()}

        raise CryptoBotAPIError(
            f"CryptoBot invoice has invalid accepted_assets: {raw!r}"
        )

    def _validate_created_fiat_invoice(
        self,
        *,
        invoice: dict[str, Any],
        selected_asset: str,
        amount_usd: Decimal,
    ) -> tuple[int, str]:
        invoice_id = invoice.get("invoice_id")
        if invoice_id is None or not str(invoice_id).isdigit():
            raise CryptoBotAPIError(
                f"CryptoBot invoice response has invalid invoice_id: {invoice!r}"
            )

        payment_url = self._invoice_payment_url(invoice)
        if not payment_url:
            raise CryptoBotAPIError(
                f"CryptoBot invoice response has no payment URL: {invoice!r}"
            )

        currency_type = invoice.get("currency_type")
        if currency_type is not None and currency_type != "fiat":
            raise CryptoBotAPIError(
                f"CryptoBot created unexpected currency_type: {currency_type!r}"
            )

        fiat = invoice.get("fiat")
        if fiat is not None and str(fiat).upper() != "USD":
            raise CryptoBotAPIError(
                f"CryptoBot created invoice in unexpected fiat: {fiat!r}"
            )

        invoice_amount = invoice.get("amount")
        if invoice_amount is not None:
            actual_amount = self._decimal(
                invoice_amount,
                field_name="amount",
            )
            if actual_amount != amount_usd:
                raise CryptoBotAPIError(
                    "CryptoBot created invoice with unexpected USD amount: "
                    f"expected={amount_usd} actual={actual_amount}"
                )

        accepted_assets = self._accepted_assets(invoice)
        if accepted_assets and selected_asset not in accepted_assets:
            raise CryptoBotAPIError(
                "CryptoBot created invoice without selected asset: "
                f"{selected_asset} not in {sorted(accepted_assets)}"
            )

        return int(invoice_id), str(payment_url)

    def _validate_paid_invoice(
        self,
        *,
        order,
        invoice_id: int,
        invoice: dict[str, Any],
    ) -> tuple[Decimal, str | None]:
        if str(invoice.get("invoice_id")) != str(invoice_id):
            return Decimal("0"), "wrong_invoice"

        if invoice.get("payload") != f"order:{order.id}":
            return Decimal("0"), "wrong_payload"

        selected_asset = self._selected_asset(order)
        currency_type = invoice.get("currency_type")

        # Совместимость со счетами, созданными до перехода на fiat-invoice.
        if currency_type is None and invoice.get("asset"):
            currency_type = "crypto"

        if currency_type == "fiat":
            fiat = invoice.get("fiat")
            if fiat is None:
                raise CryptoBotAPIError("Paid fiat invoice has no fiat field")

            if str(fiat).upper() != "USD":
                return Decimal("0"), "wrong_fiat"

            invoice_amount = invoice.get("amount")
            if invoice_amount is None:
                raise CryptoBotAPIError("Paid fiat invoice has no amount")

            amount_usd = self._decimal(
                invoice_amount,
                field_name="amount",
            )
            if amount_usd != Decimal(str(order.price_usd)):
                return Decimal("0"), "wrong_amount"

            paid_amount = invoice.get("paid_amount")
            if paid_amount is None:
                raise CryptoBotAPIError("Paid fiat invoice has no paid_amount")

            amount = self._decimal(
                paid_amount,
                field_name="paid_amount",
            )
            if amount <= 0:
                raise CryptoBotAPIError(
                    "Paid fiat invoice has non-positive paid_amount"
                )

            accepted_assets = self._accepted_assets(invoice)
            if accepted_assets and selected_asset not in accepted_assets:
                return amount, "wrong_currency"

            paid_asset = invoice.get("paid_asset")
            if paid_asset is None:
                raise CryptoBotAPIError("Paid fiat invoice has no paid_asset")

            if str(paid_asset).upper() != selected_asset:
                return amount, "wrong_currency"

            return amount, None

        if currency_type == "crypto":
            asset = invoice.get("asset")
            if asset is None:
                raise CryptoBotAPIError("Paid crypto invoice has no asset")

            if str(asset).upper() != selected_asset:
                return Decimal("0"), "wrong_currency"

            invoice_amount_raw = invoice.get("amount")
            if invoice_amount_raw is None:
                raise CryptoBotAPIError("Paid crypto invoice has no amount")

            invoice_amount = self._decimal(
                invoice_amount_raw,
                field_name="amount",
            )
            expected_amount = Decimal(str(order.expected_amount or order.price_usd))
            if invoice_amount != expected_amount:
                return invoice_amount, "wrong_amount"

            paid_asset = invoice.get("paid_asset")
            if paid_asset is not None and str(paid_asset).upper() != selected_asset:
                return invoice_amount, "wrong_currency"

            paid_amount_raw = invoice.get("paid_amount") or invoice_amount_raw
            paid_amount = self._decimal(
                paid_amount_raw,
                field_name="paid_amount",
            )
            if paid_amount <= 0:
                raise CryptoBotAPIError("Paid crypto invoice has non-positive amount")

            return paid_amount, None

        raise CryptoBotAPIError(
            f"Paid CryptoBot invoice has unsupported currency_type: {currency_type!r}"
        )

    async def _record_invalid_paid_invoice(
        self,
        *,
        order,
        invoice_id: int,
        invoice: dict[str, Any],
        amount: Decimal,
        reason: str,
        raw_payload: str,
    ) -> dict[str, Any]:
        paid_asset = invoice.get("paid_asset") or invoice.get("asset")
        currency: str | None = None

        if paid_asset is not None:
            try:
                currency = CurrencyCode(str(paid_asset).upper()).value
            except ValueError:
                currency = None

        event, payment, _ = await PaymentEventService(
            self.session
        ).process_invalid_event(
            order_id=order.id,
            amount=amount,
            currency=currency,
            network=None,
            provider="cryptobot",
            event_type="invoice_paid_invalid",
            reason=reason,
            external_event_id=f"cryptobot:{invoice_id}",
            txid=None,
            raw_payload=raw_payload,
        )

        return {
            "invoice": invoice,
            "event": event,
            "payment": payment,
            "subscription": None,
            "config_uri": None,
            "order_status": order.status.value,
            "validation_error": reason,
        }

    async def ensure_invoice_for_order(
        self,
        order_id: int,
    ) -> dict[str, Any]:
        if not self.settings.cryptobot_enabled:
            raise CryptoBotAPIError("CryptoBot integration is disabled")

        order = await self.order_repository.get_by_id(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")

        existing_invoice_id = self._invoice_id_from_order(order)
        if existing_invoice_id is not None and order.destination_address:
            return {
                "invoice_id": existing_invoice_id,
                "bot_invoice_url": order.destination_address,
                "pay_url": order.destination_address,
                "status": "existing",
            }

        selected_asset = self._selected_asset(order)
        amount_usd = Decimal(str(order.price_usd)).quantize(Decimal("0.01"))

        invoice = await self._client().create_invoice(
            fiat="USD",
            accepted_assets=selected_asset,
            amount=amount_usd,
            description=f"PresentVPN order #{order.id}",
            payload=f"order:{order.id}",
            expires_in=self.settings.cryptobot_expires_in,
        )

        invoice_id, payment_url = self._validate_created_fiat_invoice(
            invoice=invoice,
            selected_asset=selected_asset,
            amount_usd=amount_usd,
        )

        # Для fiat-invoice точное количество криптовалюты определяет
        # CryptoBot. Цена услуги остаётся в order.price_usd.
        order.expected_amount = None
        order.expected_currency = CurrencyCode(selected_asset)
        order.expected_network = None
        order.destination_address = payment_url
        order.destination_memo_tag = str(invoice_id)
        order.comment = json.dumps(
            {
                "provider": "cryptobot",
                "invoice_id": str(invoice_id),
                "hash": invoice.get("hash"),
                "currency_type": "fiat",
                "fiat": "USD",
                "amount_usd": str(amount_usd),
                "accepted_assets": selected_asset,
                "bot_invoice_url": invoice.get("bot_invoice_url"),
                "pay_url": payment_url,
                "mini_app_invoice_url": invoice.get("mini_app_invoice_url"),
                "web_app_invoice_url": invoice.get("web_app_invoice_url"),
            },
            ensure_ascii=False,
        )

        await self.session.commit()
        return invoice

    async def sync_paid_invoice_and_activate(self, order_id: int):
        order = await self.order_repository.get_by_id(order_id)
        if order is None:
            return None

        invoice_id = self._invoice_id_from_order(order)
        if invoice_id is None:
            return None

        invoice = await self._client().get_invoice(invoice_id)
        if not invoice:
            return None

        if invoice.get("status") != "paid":
            return invoice

        raw_payload = json.dumps(invoice, ensure_ascii=False)
        amount, validation_error = self._validate_paid_invoice(
            order=order,
            invoice_id=invoice_id,
            invoice=invoice,
        )

        if validation_error is not None:
            return await self._record_invalid_paid_invoice(
                order=order,
                invoice_id=invoice_id,
                invoice=invoice,
                amount=amount,
                reason=validation_error,
                raw_payload=raw_payload,
            )

        activation_service = PaymentActivationService(self.session)
        (
            event,
            payment,
            subscription,
            config_uri,
        ) = await activation_service.process_confirmed_payment_event_and_activate(
            order_id=order.id,
            amount=amount,
            provider="cryptobot",
            event_type="invoice_paid",
            external_event_id=f"cryptobot:{invoice_id}",
            txid=None,
            raw_payload=raw_payload,
        )

        return {
            "invoice": invoice,
            "event": event,
            "payment": payment,
            "subscription": subscription,
            "config_uri": config_uri,
            "order_status": (OrderStatus.ACTIVATED.value if subscription else None),
        }
