from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.payment_adapters.cryptobot import CryptoBotAPIError
from app.services.cryptobot_payment_service import CryptoBotPaymentService
from app.services.order_service import OrderService
from app.services.payment_check_service import PaymentCheckService

router = Router()


@router.callback_query(F.data.startswith("check_payment:"))
async def check_payment_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    order_id_raw = callback.data.replace("check_payment:", "")

    if not order_id_raw.isdigit():
        await callback.answer("Invalid order", show_alert=True)
        return

    order_id = int(order_id_raw)

    order = await OrderService(session).get_order_for_telegram_user(
        order_id=order_id,
        telegram_id=callback.from_user.id,
    )
    if order is None:
        await callback.answer(
            "Order not found",
            show_alert=True,
        )
        return

    try:
        await CryptoBotPaymentService(session).sync_paid_invoice_and_activate(order_id)
    except CryptoBotAPIError:
        await callback.message.answer(
            "Could not check the payment through CryptoBot. Try again in a few seconds."
        )
        await callback.answer()
        return

    result = await PaymentCheckService(session).check_order_payment(order_id)

    if result.status == "waiting_payment":
        text = "Payment has not been found yet. If you have already paid, check again in a few seconds."

    elif result.status == "activated":
        text = "Payment confirmed. VPN access is active. Open “My Subscription” and click “Connect VPN”."

    elif result.status == "paid_waiting_activation":
        text = "Payment confirmed. Access is being activated."

    elif result.status == "invalid_payment":
        reason = result.error_message or "invalid_payment"

        if reason == "wrong_amount":
            text = "Payment found, but the amount does not match the order."
        elif reason == "wrong_network":
            text = "Payment found, but it was sent through the wrong network."
        elif reason == "wrong_currency":
            text = "Payment found, but the currency does not match the order."
        else:
            text = "Payment found, but it is invalid. Contact support."

    elif result.status == "expired":
        text = "The order has expired. Create a new order."

    elif result.status == "late_payment":
        text = "Payment found, but it arrived after the order expired. Manual review is required."

    elif result.status == "activation_failed":
        text = "Payment found, but access activation was not completed. Manual review is required."

    else:
        text = "Could not determine the order status. Contact support."

    await callback.message.answer(text)
    await callback.answer()
