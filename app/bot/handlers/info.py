from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.main_menu import back_to_main_menu_keyboard

router = Router()


@router.callback_query(F.data == "download_vpn")
async def download_vpn_callback(callback: CallbackQuery):
    text = (
        "Скачать VPN-клиент\n\n"
        "Рекомендуемый клиент:\n"
        "Happ VPN\n\n"
        "Резервный вариант:\n"
        "v2RayTun\n\n"
        "После установки клиента скопируй VLESS-конфиг из раздела «Моя подписка» "
        "и импортируй его в приложение."
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_to_main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "faq")
async def faq_callback(callback: CallbackQuery):
    text = (
        "FAQ\n\n"
        "1. Что делать после оплаты?\n"
        "Нажми кнопку «Я оплатил / Проверить оплату» в сообщении с заказом.\n\n"
        "2. Что если платеж не найден?\n"
        "Подожди немного и проверь еще раз. Иногда транзакция появляется не сразу.\n\n"
        "3. Что если отправил не ту сумму?\n"
        "Система отметит платеж как некорректный. Такой случай требует ручной проверки.\n\n"
        "4. Что если отправил не в той сети?\n"
        "Автоматическая активация не выполнится. Нужно обратиться в поддержку.\n\n"
        "5. Где получить конфиг повторно?\n"
        "В разделе «Моя подписка»."
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_to_main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def support_callback(callback: CallbackQuery):
    text = (
        "Поддержка\n\n"
        "Если возникла проблема с оплатой или подключением, напиши администратору.\n\n"
        "Перед обращением подготовь:\n"
        "- Order ID\n"
        "- txid транзакции\n"
        "- сеть оплаты\n"
        "- сумму оплаты"
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_to_main_menu_keyboard(),
    )
    await callback.answer()