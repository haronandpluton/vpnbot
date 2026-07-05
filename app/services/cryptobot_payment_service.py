from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import CurrencyCode
from app.config.settings import get_settings
from app.database.repositories.orders import OrderRepository
from app.payment_adapters.cryptobot import CryptoBotAPIError, CryptoBotClient
from app.payment_core.enums.order_status import OrderStatus
from app.services.payment_activation_service import PaymentActivationService


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

    async def ensure_invoice_for_order(self, order_id: int) -> dict[str, Any]:
        if not self.settings.cryptobot_enabled:
            raise CryptoBotAPIError("CryptoBot integration is disabled")

        order = await self.order_repository.get_by_id(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")

        existing_invoice_id = self._invoice_id_from_order(order)
        if existing_invoice_id is not None and order.destination_address:
            return {
                "invoice_id": existing_invoice_id,
                "pay_url": order.destination_address,
                "status": "existing",
            }

        amount = Decimal(str(order.expected_amount or order.price_usd)).quantize(
            Decimal("0.01")
        )
        asset = self.settings.cryptobot_asset.strip().upper() or "USDT"

        invoice = await self._client().create_invoice(
            asset=asset,
            amount=amount,
            description=f"PresentVPN order #{order.id}",
            payload=f"order:{order.id}",
            expires_in=self.settings.cryptobot_expires_in,
        )

        invoice_id = invoice.get("invoice_id")
        pay_url = invoice.get("pay_url") or invoice.get("bot_invoice_url")
        if invoice_id is None or not pay_url:
            raise CryptoBotAPIError(f"CryptoBot invoice response is incomplete: {invoice!r}")

        order.expected_amount = Decimal(str(invoice.get("amount") or amount))
        order.expected_currency = CurrencyCode.USDT
        order.expected_network = None
        order.destination_address = str(pay_url)
        order.destination_memo_tag = str(invoice_id)
        order.comment = json.dumps(
            {
                "provider": "cryptobot",
                "invoice_id": str(invoice_id),
                "hash": invoice.get("hash"),
                "pay_url": pay_url,
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

        amount = Decimal(str(invoice.get("amount") or order.expected_amount or "0"))
        raw_payload = json.dumps(invoice, ensure_ascii=False)

        activation_service = PaymentActivationService(self.session)
        event, payment, subscription, config_uri = (
            await activation_service.process_confirmed_payment_event_and_activate(
                order_id=order.id,
                amount=amount,
                provider="cryptobot",
                event_type="invoice_paid",
                external_event_id=f"cryptobot:{invoice_id}",
                txid=None,
                raw_payload=raw_payload,
            )
        )

        return {
            "invoice": invoice,
            "event": event,
            "payment": payment,
            "subscription": subscription,
            "config_uri": config_uri,
            "order_status": OrderStatus.ACTIVATED.value if subscription else None,
        }
