from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order
from app.payment_adapters.base import NormalizedTransaction
from app.payment_core.enums.order_status import OrderStatus
from app.services.payment_activation_service import PaymentActivationService
from app.services.payment_event_service import PaymentEventService


class PaymentPollingProcessor:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.activation_service = PaymentActivationService(session)
        self.payment_event_service = PaymentEventService(session)

    async def process_transaction(self, tx: NormalizedTransaction):
        order = await self._find_matching_order(tx)

        if order is not None:
            event, payment, subscription, config_uri = (
                await self.activation_service.process_confirmed_payment_event_and_activate(
                    order_id=order.id,
                    amount=tx.amount,
                    provider=tx.provider or "unknown",
                    event_type="payment_confirmed",
                    external_event_id=tx.txid,
                    txid=tx.txid,
                    address_from=tx.address_from,
                    address_to=tx.address_to,
                    memo_tag=tx.memo_tag,
                    confirmations=tx.confirmations,
                    raw_payload=str(tx.raw_payload),
                )
            )

            print("TX PROCESSED:")
            print("txid =", tx.txid)
            print("order_id =", order.id)
            print("event_id =", event.id)
            print("payment_id =", None if payment is None else payment.id)
            print("subscription_id =", subscription.id)
            print("config_uri =", config_uri)

            return event, payment, subscription, config_uri

        invalid_amount_order = await self._find_invalid_amount_order(tx)

        if invalid_amount_order is not None:
            event, payment, invalid_order = (
                await self.payment_event_service.process_invalid_event(
                    order_id=invalid_amount_order.id,
                    amount=tx.amount,
                    currency=tx.currency,
                    network=tx.network,
                    provider=tx.provider or "unknown",
                    event_type="payment_invalid",
                    reason="wrong_amount",
                    external_event_id=tx.txid,
                    txid=tx.txid,
                    address_from=tx.address_from,
                    address_to=tx.address_to,
                    memo_tag=tx.memo_tag,
                    confirmations=tx.confirmations,
                    raw_payload=str(tx.raw_payload),
                )
            )

            print("INVALID TX PROCESSED:")
            print("reason = wrong_amount")
            print("txid =", tx.txid)
            print("order_id =", invalid_order.id)
            print("event_id =", event.id)
            print("payment_id =", payment.id)

            return event, payment, None, None

        invalid_network_order = await self._find_invalid_network_order(tx)

        if invalid_network_order is not None:
            event, payment, invalid_order = (
                await self.payment_event_service.process_invalid_event(
                    order_id=invalid_network_order.id,
                    amount=tx.amount,
                    currency=tx.currency,
                    network=tx.network,
                    provider=tx.provider or "unknown",
                    event_type="payment_invalid",
                    reason="wrong_network",
                    external_event_id=tx.txid,
                    txid=tx.txid,
                    address_from=tx.address_from,
                    address_to=tx.address_to,
                    memo_tag=tx.memo_tag,
                    confirmations=tx.confirmations,
                    raw_payload=str(tx.raw_payload),
                )
            )

            print("INVALID TX PROCESSED:")
            print("reason = wrong_network")
            print("txid =", tx.txid)
            print("order_id =", invalid_order.id)
            print("event_id =", event.id)
            print("payment_id =", payment.id)

            return event, payment, None, None

        print("NO MATCHING ORDER FOR TX:")
        print("txid =", tx.txid)
        print("amount =", tx.amount)
        print("currency =", tx.currency)
        print("network =", tx.network)
        return None

    async def process_transactions(self, transactions: list[NormalizedTransaction]) -> list:
        results = []

        for tx in transactions:
            result = await self.process_transaction(tx)
            if result is not None:
                results.append(result)

        return results

    async def _find_matching_order(self, tx: NormalizedTransaction) -> Order | None:
        now = datetime.now(timezone.utc)
        tx_amount = Decimal(tx.amount)

        exact_stmt = (
            select(Order)
            .where(
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                Order.expected_currency == tx.currency,
                Order.expected_network == tx.network,
                Order.expected_amount == tx_amount,
                Order.destination_address == tx.address_to,
            )
            .order_by(Order.created_at.asc())
            .limit(1)
        )

        exact_result = await self.session.execute(exact_stmt)
        exact_order = exact_result.scalar_one_or_none()

        if exact_order is not None:
            return exact_order

        fallback_stmt = (
            select(Order)
            .where(
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                Order.expected_currency == tx.currency,
                Order.expected_network == tx.network,
                Order.expected_amount.is_(None),
                Order.price_usd == tx_amount,
                Order.destination_address == tx.address_to,
            )
            .order_by(Order.created_at.asc())
            .limit(1)
        )

        fallback_result = await self.session.execute(fallback_stmt)
        return fallback_result.scalar_one_or_none()

    async def _find_invalid_amount_order(self, tx: NormalizedTransaction) -> Order | None:
        now = datetime.now(timezone.utc)
        tx_amount = Decimal(tx.amount)

        stmt = (
            select(Order)
            .where(
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                Order.expected_currency == tx.currency,
                Order.expected_network == tx.network,
                Order.expected_amount.is_not(None),
                Order.expected_amount != tx_amount,
                Order.destination_address == tx.address_to,
            )
            .order_by(Order.created_at.asc())
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _find_invalid_network_order(self, tx: NormalizedTransaction) -> Order | None:
        now = datetime.now(timezone.utc)
        tx_amount = Decimal(tx.amount)

        stmt = (
            select(Order)
            .where(
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                Order.expected_currency == tx.currency,
                Order.expected_network != tx.network,
                Order.expected_amount == tx_amount,
                Order.destination_address == tx.address_to,
            )
            .order_by(Order.created_at.asc())
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()