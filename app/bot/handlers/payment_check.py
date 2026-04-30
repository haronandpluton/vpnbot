from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.payment_check_service import PaymentCheckService

router = Router()


@router.callback_query(F.data.startswith("check_payment:"))
async def check_payment_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    order_id_raw = callback.data.replace("check_payment:", "")

    if not order_id_raw.isdigit():
        await callback.answer("Некорректный заказ", show_alert=True)
        return

    result = await PaymentCheckService(session).check_order_payment(int(order_id_raw))

    if result.status == "waiting_payment":
        text = "Платеж пока не найден. Если ты уже оплатил, проверь еще раз через несколько секунд."

    elif result.status == "activated":
        text = "Оплата подтверждена. VPN-доступ активирован."

    elif result.status == "paid_waiting_activation":
        text = "Оплата подтверждена. Доступ активируется."

    elif result.status == "invalid_payment":
        reason = result.error_message or "invalid_payment"

        if reason == "wrong_amount":
            text = "Платеж найден, но сумма не совпадает с заказом."
        elif reason == "wrong_network":
            text = "Платеж найден, но отправлен не в той сети."
        elif reason == "wrong_currency":
            text = "Платеж найден, но валюта не совпадает с заказом."
        else:
            text = "Платеж найден, но он некорректный. Обратись в поддержку."

    elif result.status == "expired":
        text = "Срок действия заказа истек. Создай новый заказ."

    elif result.status == "late_payment":
        text = "Платеж найден, но пришел после истечения срока заказа. Нужна ручная проверка."

    elif result.status == "activation_failed":
        text = "Оплата найдена, но активация доступа не завершилась. Нужна ручная проверка."

    else:
        text = "Статус заказа не удалось определить. Обратись в поддержку."

    await callback.message.answer(text)
    await callback.answer()