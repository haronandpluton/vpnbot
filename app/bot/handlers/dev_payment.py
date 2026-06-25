from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order
from app.payment_adapters.base import NormalizedTransaction
from app.payment_core.enums.order_status import OrderStatus
from app.payment_polling.processor import PaymentPollingProcessor

router = Router()


def _enum_value(value):
    if hasattr(value, "value"):
        return value.value
    return value


def _model_id(obj):
    if obj is None:
        return None

    state = inspect(obj)

    if state.identity:
        return state.identity[0]

    return getattr(obj, "id", None)


@router.callback_query(F.data.startswith("dev_confirm_payment:"))
async def dev_confirm_payment_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    order_id_raw = callback.data.replace("dev_confirm_payment:", "")

    if not order_id_raw.isdigit():
        await callback.answer("Некорректный заказ", show_alert=True)
        return

    order_id = int(order_id_raw)

    result = await session.execute(
        select(Order).where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()

    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    order_id_for_text = order.id
    order_status = order.status
    destination_address = order.destination_address
    expected_amount = order.expected_amount
    price_usd = order.price_usd
    expected_currency = _enum_value(order.expected_currency)
    expected_network = _enum_value(order.expected_network)

    if order_status == OrderStatus.ACTIVATED:
        await callback.message.answer(
            "Заказ уже активирован.\n\n"
            "Отправь команду /my_subscription, чтобы получить конфиг."
        )
        await callback.answer()
        return

    if order_status != OrderStatus.WAITING_PAYMENT:
        await callback.message.answer(
            "Mock-подтверждение доступно только для заказа в статусе waiting_payment.\n\n"
            f"Текущий статус заказа: {order_status.value}"
        )
        await callback.answer()
        return

    if destination_address is None:
        destination_address = f"dev_mock_receiver_order_{order_id_for_text}"
        order.destination_address = destination_address
        await session.commit()

    amount = expected_amount or price_usd
    currency = expected_currency
    network = expected_network

    tx = NormalizedTransaction(
        txid=f"dev_confirm_txid_order_{order_id_for_text}",
        amount=Decimal(amount),
        currency=currency,
        network=network,
        address_from="dev_mock_sender_wallet",
        address_to=destination_address,
        confirmations=3,
        provider="mock",
        raw_payload={
            "source": "dev_confirm_payment_callback",
            "order_id": order_id_for_text,
            "telegram_id": callback.from_user.id,
            "amount": str(amount),
            "currency": currency,
            "network": network,
        },
    )

    processor = PaymentPollingProcessor(session)
    processed_result = await processor.process_transaction(tx)

    if processed_result is None:
        await callback.message.answer(
            "Mock-транзакция создана, но заказ не был найден processor-ом.\n\n"
            "Проверь expected_amount / currency / network / destination_address."
        )
        await callback.answer()
        return

    event, payment, subscription, config_uri = processed_result

    event_id = _model_id(event)
    payment_id = _model_id(payment)
    subscription_id = _model_id(subscription)

    if subscription is None or config_uri is None:
        await callback.message.answer(
            "Mock-платеж обработан, но подписка не была активирована.\n\n"
            f"Event ID: {event_id}\n"
            f"Payment ID: {payment_id if payment_id else 'None'}\n\n"
            "Проверь логи processor-а."
        )
        await callback.answer()
        return

    text = (
        "DEV mock-платеж подтвержден.\n\n"
        f"Order ID: {order_id_for_text}\n"
        f"Payment ID: {payment_id}\n"
        f"Event ID: {event_id}\n"
        f"Subscription ID: {subscription_id}\n\n"
        "VPN-доступ активирован.\n\n"
        "Теперь можно отправить:\n"
        "/my_subscription"
    )

    await callback.message.answer(text)
    await callback.answer()