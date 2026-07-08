from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import back_to_main_menu_keyboard
from app.config.settings import get_settings
from app.database.repositories.users import UserRepository
from app.services.my_subscription_service import MySubscriptionService

router = Router()

HAPP_SITE_URL = "https://www.happ.su/main/ru"
HAPP_IOS_URL = "https://apps.apple.com/us/app/happ-proxy-utility/id6504287215"
HAPP_ANDROID_URL = "https://play.google.com/store/apps/details?id=com.happproxy"
HAPP_DESKTOP_RELEASES_URL = "https://github.com/Happ-proxy/happ-desktop/releases"


def download_platform_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="iPhone / iOS",
                    callback_data="download_vpn:ios",
                ),
                InlineKeyboardButton(
                    text="Android",
                    callback_data="download_vpn:android",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Windows",
                    callback_data="download_vpn:windows",
                ),
                InlineKeyboardButton(
                    text="macOS",
                    callback_data="download_vpn:macos",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад в меню",
                    callback_data="back_to_main_menu",
                ),
            ],
        ]
    )


def installed_continue_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Купить VPN",
                    callback_data="buy_vpn",
                ),
                InlineKeyboardButton(
                    text="Моя подписка",
                    callback_data="my_subscription",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад к платформам",
                    callback_data="download_vpn",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад в меню",
                    callback_data="back_to_main_menu",
                ),
            ],
        ]
    )


def platform_download_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Скачать Happ",
                    url=url,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Я установил(а)",
                    callback_data="download_vpn:installed",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад к платформам",
                    callback_data="download_vpn",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад в меню",
                    callback_data="back_to_main_menu",
                ),
            ],
        ]
    )


def support_keyboard() -> InlineKeyboardMarkup:
    settings = get_settings()
    support_username = settings.support_username.strip().lstrip("@")

    rows = [
        [
            InlineKeyboardButton(
                text="Проблема с оплатой",
                callback_data="support:payment",
            ),
        ],
        [
            InlineKeyboardButton(
                text="VPN не подключается",
                callback_data="support:vpn",
            ),
        ],
    ]

    if support_username:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Написать в поддержку",
                    url=f"https://t.me/{support_username}",
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Назад в меню",
                callback_data="back_to_main_menu",
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назад в поддержку",
                    callback_data="support",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад в меню",
                    callback_data="back_to_main_menu",
                ),
            ],
        ]
    )

@router.message(Command("faq", "info"))
async def faq_command(message: Message):
    text = (
        "FAQ\n\n"
        "1. Как начать пользоваться VPN?\n"
        "Установи Happ через раздел «Скачать VPN», купи подписку, затем открой «Моя подписка» "
        "и нажми «Подключить VPN».\n\n"
        "2. Где получить доступ после оплаты?\n"
        "В разделе «Моя подписка». Там будет кнопка «Подключить VPN».\n\n"
        "3. Нужно ли копировать VLESS-ключ вручную?\n"
        "Обычно нет. Бот выдаёт страницу подключения, через которую Happ должен импортировать "
        "подписку автоматически.\n\n"
        "4. Что делать, если Happ не открылся автоматически?\n"
        "На странице подключения нажми «Открыть вручную». Если не помогло — скопируй резервную "
        "ссылку и добавь её в Happ как subscription.\n\n"
        "5. Что делать, если оплатил, но доступ не появился?\n"
        "Открой сообщение с заказом и нажми «Проверить оплату». Если платёж всё равно не найден, "
        "обратись в поддержку и пришли Order ID, txid, сумму и сеть.\n\n"
        "6. Что если отправил не ту сумму или не в той сети?\n"
        "Автоматическая активация может не пройти. Такой платёж требует ручной проверки.\n\n"
        "7. Как продлить подписку?\n"
        "Открой «Моя подписка» и нажми «Продлить подписку». После оплаты срок будет добавлен "
        "к текущей активной подписке.\n\n"
        "8. Что будет после окончания подписки?\n"
        "Доступ перестанет работать. Для восстановления нужно продлить подписку."
    )

    await message.answer(
        text,
        reply_markup=back_to_main_menu_keyboard(),
    )


@router.message(Command("help"))
async def help_command(message: Message):
    settings = get_settings()
    support_username = settings.support_username.strip()

    contact_text = (
        f"Контакт поддержки: @{support_username.lstrip('@')}"
        if support_username
        else "Контакт поддержки пока не указан в настройках."
    )

    text = (
        "Поддержка\n\n"
        "Если возникла проблема, подготовь данные:\n\n"
        "• Order ID;\n"
        "• txid транзакции, если вопрос по оплате;\n"
        "• сумму и сеть оплаты;\n"
        "• модель устройства;\n"
        "• скрин ошибки;\n"
        "• время попытки подключения.\n\n"
        f"{contact_text}\n\n"
        "Правила сервиса: /rules"
    )

    await message.answer(
        text,
        reply_markup=support_keyboard(),
    )


@router.message(Command("profile"))
async def profile_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.")
        return

    user = await UserRepository(session).get_by_telegram_id(message.from_user.id)
    subscription = await MySubscriptionService(
        session,
    ).get_active_subscription_by_telegram_id(
        telegram_id=message.from_user.id,
    )

    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    db_status = "создан" if user is not None else "не создан"

    subscription_status_map = {
        "active": "активна",
        "user_not_found": "профиль не найден",
        "subscription_not_found": "активная подписка не найдена",
        "subscription_expired": "истекла",
        "subscription_not_active": "не активна",
    }

    subscription_status = subscription_status_map.get(
        subscription.status,
        "не удалось определить",
    )

    text = (
        "Профиль\n\n"
        f"Telegram ID: {message.from_user.id}\n"
        f"Username: {username}\n"
        f"Профиль в БД: {db_status}\n"
        "Баланс: пока не подключён\n"
        f"Подписка: {subscription_status}"
    )

    await message.answer(
        text,
        reply_markup=back_to_main_menu_keyboard(),
    )


@router.message(Command("present"))
async def present_command(message: Message):
    text = (
        "Подарочная программа\n\n"
        "Раздел подготовлен для будущих подарочных подписок и приглашений.\n\n"
        "Сейчас подарочная программа ещё не активна. "
        "Купить VPN для себя можно через /buy."
    )

    await message.answer(
        text,
        reply_markup=back_to_main_menu_keyboard(),
    )
    

@router.callback_query(F.data == "download_vpn")
async def download_vpn_callback(callback: CallbackQuery):
    text = (
        "Скачать VPN\n\n"
        "Перед оплатой или подключением установи VPN-клиент.\n\n"
        "Основной клиент: Happ.\n"
        "Он используется для импорта подписки и подключения к VPN.\n\n"
        "Выбери свою платформу:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=download_platform_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "download_vpn:ios")
async def download_vpn_ios_callback(callback: CallbackQuery):
    text = (
        "Happ для iPhone / iOS\n\n"
        "1. Нажми «Скачать Happ».\n"
        "2. Установи приложение из App Store.\n"
        "3. Вернись в бот.\n"
        "4. Если подписка уже активна — открой «Моя подписка» и нажми «Подключить VPN».\n\n"
        "После нажатия «Подключить VPN» откроется страница подключения. "
        "Happ должен автоматически импортировать подписку."
    )

    await callback.message.edit_text(
        text,
        reply_markup=platform_download_keyboard(HAPP_IOS_URL),
    )
    await callback.answer()


@router.callback_query(F.data == "download_vpn:android")
async def download_vpn_android_callback(callback: CallbackQuery):
    text = (
        "Happ для Android\n\n"
        "1. Нажми «Скачать Happ».\n"
        "2. Установи приложение из Google Play.\n"
        "3. Вернись в бот.\n"
        "4. Если подписка уже активна — открой «Моя подписка» и нажми «Подключить VPN».\n\n"
        "Если автооткрытие Happ не сработает, на странице подключения будет кнопка "
        "«Открыть вручную» и резервная ссылка."
    )

    await callback.message.edit_text(
        text,
        reply_markup=platform_download_keyboard(HAPP_ANDROID_URL),
    )
    await callback.answer()


@router.callback_query(F.data == "download_vpn:windows")
async def download_vpn_windows_callback(callback: CallbackQuery):
    text = (
        "Happ для Windows\n\n"
        "1. Нажми «Скачать Happ».\n"
        "2. Скачай Windows-версию из Releases.\n"
        "3. Установи приложение.\n"
        "4. Вернись в бот.\n"
        "5. Открой «Моя подписка» и нажми «Подключить VPN».\n\n"
        "Если автоматический импорт не сработает, скопируй резервную ссылку со страницы подключения "
        "и добавь её в Happ как subscription."
    )

    await callback.message.edit_text(
        text,
        reply_markup=platform_download_keyboard(HAPP_DESKTOP_RELEASES_URL),
    )
    await callback.answer()


@router.callback_query(F.data == "download_vpn:macos")
async def download_vpn_macos_callback(callback: CallbackQuery):
    text = (
        "Happ для macOS\n\n"
        "1. Нажми «Скачать Happ».\n"
        "2. Скачай macOS-версию из Releases.\n"
        "3. Установи приложение.\n"
        "4. Вернись в бот.\n"
        "5. Открой «Моя подписка» и нажми «Подключить VPN».\n\n"
        "Если автоматический импорт не сработает, используй резервную ссылку со страницы подключения."
    )

    await callback.message.edit_text(
        text,
        reply_markup=platform_download_keyboard(HAPP_DESKTOP_RELEASES_URL),
    )
    await callback.answer()


@router.callback_query(F.data == "download_vpn:installed")
async def download_vpn_installed_callback(callback: CallbackQuery):
    text = (
        "Клиент установлен\n\n"
        "Дальше:\n\n"
        "1. Если подписки ещё нет — нажми «Купить VPN».\n"
        "2. Если подписка уже активна — нажми «Моя подписка».\n"
        "3. В разделе подписки нажми «Подключить VPN».\n\n"
        "Бот откроет страницу подключения, а Happ должен импортировать подписку автоматически."
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=installed_continue_keyboard(),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise

    await callback.answer()


@router.callback_query(F.data == "faq")
async def faq_callback(callback: CallbackQuery):
    text = (
        "FAQ\n\n"
        "1. Как начать пользоваться VPN?\n"
        "Установи Happ через раздел «Скачать VPN», купи подписку, затем открой «Моя подписка» "
        "и нажми «Подключить VPN».\n\n"
        "2. Где получить доступ после оплаты?\n"
        "В разделе «Моя подписка». Там будет кнопка «Подключить VPN».\n\n"
        "3. Нужно ли копировать VLESS-ключ вручную?\n"
        "Обычно нет. Бот выдаёт страницу подключения, через которую Happ должен импортировать "
        "подписку автоматически.\n\n"
        "4. Что делать, если Happ не открылся автоматически?\n"
        "На странице подключения нажми «Открыть вручную». Если не помогло — скопируй резервную "
        "ссылку и добавь её в Happ как subscription.\n\n"
        "5. Что делать, если оплатил, но доступ не появился?\n"
        "Открой сообщение с заказом и нажми «Проверить оплату». Если платёж всё равно не найден, "
        "обратись в поддержку и пришли Order ID, txid, сумму и сеть.\n\n"
        "6. Что если отправил не ту сумму или не в той сети?\n"
        "Автоматическая активация может не пройти. Такой платёж требует ручной проверки.\n\n"
        "7. Как продлить подписку?\n"
        "Открой «Моя подписка» и нажми «Продлить подписку». После оплаты срок будет добавлен "
        "к текущей активной подписке.\n\n"
        "8. Что будет после окончания подписки?\n"
        "Доступ перестанет работать. Для восстановления нужно продлить подписку."
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_to_main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def support_callback(callback: CallbackQuery):
    settings = get_settings()
    support_username = settings.support_username.strip()

    contact_text = (
        f"Контакт поддержки: @{support_username.lstrip('@')}"
        if support_username
        else "Контакт поддержки пока не указан в настройках."
    )

    text = (
        "Поддержка\n\n"
        "Выбери тип проблемы:\n\n"
        "• Проблема с оплатой\n"
        "• VPN не подключается\n\n"
        f"{contact_text}\n\n"
        "Перед обращением подготовь Order ID, txid, сумму, сеть оплаты и скрин ошибки."
    )

    await callback.message.edit_text(
        text,
        reply_markup=support_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "support:payment")
async def support_payment_callback(callback: CallbackQuery):
    text = (
        "Проблема с оплатой\n\n"
        "Перед обращением в поддержку подготовь:\n\n"
        "1. Order ID.\n"
        "2. txid транзакции.\n"
        "3. Сумму платежа.\n"
        "4. Валюту и сеть, например USDT / TRC20.\n"
        "5. Скрин из кошелька или биржи.\n\n"
        "Частые причины проблемы:\n"
        "• отправлена не точная сумма;\n"
        "• выбрана не та сеть;\n"
        "• транзакция ещё не получила подтверждения;\n"
        "• заказ уже истёк."
    )

    await callback.message.edit_text(
        text,
        reply_markup=support_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "support:vpn")
async def support_vpn_callback(callback: CallbackQuery):
    text = (
        "VPN не подключается\n\n"
        "Проверь по порядку:\n\n"
        "1. Подписка активна в разделе «Моя подписка».\n"
        "2. Happ установлен.\n"
        "3. Ты нажал «Подключить VPN» именно из бота.\n"
        "4. На странице подключения нажал «Открыть вручную», если автооткрытие не сработало.\n"
        "5. Если сеть не работает через Wi-Fi — проверь через мобильный интернет.\n\n"
        "Для поддержки подготовь:\n"
        "• модель устройства;\n"
        "• Android / iOS / Windows / macOS;\n"
        "• скрин ошибки;\n"
        "• время попытки подключения."
    )

    await callback.message.edit_text(
        text,
        reply_markup=support_back_keyboard(),
    )
    await callback.answer()