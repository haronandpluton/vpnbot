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
                    text="Back to Menu",
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
                    text="Buy VPN",
                    callback_data="buy_vpn",
                ),
                InlineKeyboardButton(
                    text="My Subscription",
                    callback_data="my_subscription",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Back to Platforms",
                    callback_data="download_vpn",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Back to Menu",
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
                    text="Download Happ",
                    url=url,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="I Have Installed It",
                    callback_data="download_vpn:installed",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Back to Platforms",
                    callback_data="download_vpn",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Back to Menu",
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
                text="Payment Problem",
                callback_data="support:payment",
            ),
        ],
        [
            InlineKeyboardButton(
                text="VPN Does Not Connect",
                callback_data="support:vpn",
            ),
        ],
    ]

    if support_username:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Contact Support",
                    url=f"https://t.me/{support_username}",
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Back to Menu",
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
                    text="Back to Support",
                    callback_data="support",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Back to Menu",
                    callback_data="back_to_main_menu",
                ),
            ],
        ]
    )

@router.message(Command("faq", "info"))
async def faq_command(message: Message):
    text = (
        "FAQ\n\n"
        "1. How do I start using the VPN?\n"
        "Install Happ from “Download VPN”, buy a subscription, then open “My Subscription” "
        "and click “Connect VPN”.\n\n"
        "2. Where can I get access after payment?\n"
        "In “My Subscription”. You will see a “Connect VPN” button there.\n\n"
        "3. Do I need to copy the VLESS key manually?\n"
        "Usually not. The bot provides a connection page through which Happ should import "
        "the subscription automatically.\n\n"
        "4. What should I do if Happ did not open automatically?\n"
        "On the connection page, click “Open Manually”. If that does not help, copy the backup "
        "link and add it to Happ as a subscription.\n\n"
        "5. What should I do if I paid but access did not appear?\n"
        "Open the order message and click “Check Payment”. If the payment is still not found, "
        "contact support and send the Order ID, txid, amount, and network.\n\n"
        "6. What if I sent the wrong amount or used the wrong network?\n"
        "Automatic activation may fail. This payment will require manual review.\n\n"
        "7. How do I renew my subscription?\n"
        "Open “My Subscription” and click “Renew Subscription”. After payment, the new period will be added "
        "to your current active subscription.\n\n"
        "8. What happens after the subscription expires?\n"
        "Access will stop working. Renew the subscription to restore it."
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
        f"Support contact: @{support_username.lstrip('@')}"
        if support_username
        else "The support contact has not been configured yet."
    )

    text = (
        "Support\n\n"
        "If you have a problem, prepare the following information:\n\n"
        "• Order ID;\n"
        "• transaction txid, if the issue concerns payment;\n"
        "• payment amount and network;\n"
        "• device model;\n"
        "• screenshot of the error;\n"
        "• time of the connection attempt.\n\n"
        f"{contact_text}\n\n"
        "Service rules: /rules"
    )

    await message.answer(
        text,
        reply_markup=support_keyboard(),
    )


@router.message(Command("paysupport"))
async def paysupport_command(message: Message):
    settings = get_settings()
    support_username = settings.support_username.strip()

    contact_text = (
        f"Support contact: @{support_username.lstrip('@')}"
        if support_username
        else "The support contact has not been configured yet."
    )

    text = (
        "Telegram Stars Payment Support\n\n"
        "If Stars were deducted but VPN access was not activated, "
        "do not make another payment.\n\n"
        "Before contacting support, prepare:\n\n"
        "1. Order ID.\n"
        "2. Number of Stars paid.\n"
        "3. Approximate payment date and time.\n"
        "4. Screenshot of the Telegram payment receipt.\n"
        "5. Description of what happened after payment.\n\n"
        f"{contact_text}\n\n"
        "You can also open “Payment Problem” below."
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
        await message.answer("Could not identify the user.")
        return

    user = await UserRepository(session).get_by_telegram_id(message.from_user.id)
    subscription = await MySubscriptionService(
        session,
    ).get_active_subscription_by_telegram_id(
        telegram_id=message.from_user.id,
    )

    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    db_status = "created" if user is not None else "not created"

    subscription_status_map = {
        "active": "active",
        "user_not_found": "profile not found",
        "subscription_not_found": "no active subscription found",
        "subscription_expired": "expired",
        "subscription_not_active": "not active",
    }

    subscription_status = subscription_status_map.get(
        subscription.status,
        "could not determine",
    )

    text = (
        "Profile\n\n"
        f"Telegram ID: {message.from_user.id}\n"
        f"Username: {username}\n"
        f"Database profile: {db_status}\n"
        "Balance: not available yet\n"
        f"Subscription: {subscription_status}"
    )

    await message.answer(
        text,
        reply_markup=back_to_main_menu_keyboard(),
    )


@router.message(Command("present"))
async def present_command(message: Message):
    text = (
        "Present Program\n\n"
        "This section is reserved for future gift subscriptions and invitations.\n\n"
        "The present program is not active yet. "
        "You can buy VPN access for yourself with /buy."
    )

    await message.answer(
        text,
        reply_markup=back_to_main_menu_keyboard(),
    )
    

@router.callback_query(F.data == "download_vpn")
async def download_vpn_callback(callback: CallbackQuery):
    text = (
        "Download VPN\n\n"
        "Install a VPN client before payment or connection.\n\n"
        "Recommended client: Happ.\n"
        "It is used to import the subscription and connect to the VPN.\n\n"
        "Choose your platform:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=download_platform_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "download_vpn:ios")
async def download_vpn_ios_callback(callback: CallbackQuery):
    text = (
        "Happ for iPhone / iOS\n\n"
        "1. Click “Download Happ”.\n"
        "2. Install the app from the App Store.\n"
        "3. Return to the bot.\n"
        "4. If your subscription is already active, open “My Subscription” and click “Connect VPN”.\n\n"
        "After you click “Connect VPN”, the connection page will open. "
        "Happ should import the subscription automatically."
    )

    await callback.message.edit_text(
        text,
        reply_markup=platform_download_keyboard(HAPP_IOS_URL),
    )
    await callback.answer()


@router.callback_query(F.data == "download_vpn:android")
async def download_vpn_android_callback(callback: CallbackQuery):
    text = (
        "Happ for Android\n\n"
        "1. Click “Download Happ”.\n"
        "2. Install the app from Google Play.\n"
        "3. Return to the bot.\n"
        "4. If your subscription is already active, open “My Subscription” and click “Connect VPN”.\n\n"
        "If Happ does not open automatically, the connection page will have an "
        "“Open Manually” button and a backup link."
    )

    await callback.message.edit_text(
        text,
        reply_markup=platform_download_keyboard(HAPP_ANDROID_URL),
    )
    await callback.answer()


@router.callback_query(F.data == "download_vpn:windows")
async def download_vpn_windows_callback(callback: CallbackQuery):
    text = (
        "Happ for Windows\n\n"
        "1. Click “Download Happ”.\n"
        "2. Download the Windows version from Releases.\n"
        "3. Install the app.\n"
        "4. Return to the bot.\n"
        "5. Open “My Subscription” and click “Connect VPN”.\n\n"
        "If automatic import does not work, copy the backup link from the connection page "
        "and add it to Happ as a subscription."
    )

    await callback.message.edit_text(
        text,
        reply_markup=platform_download_keyboard(HAPP_DESKTOP_RELEASES_URL),
    )
    await callback.answer()


@router.callback_query(F.data == "download_vpn:macos")
async def download_vpn_macos_callback(callback: CallbackQuery):
    text = (
        "Happ for macOS\n\n"
        "1. Click “Download Happ”.\n"
        "2. Download the macOS version from Releases.\n"
        "3. Install the app.\n"
        "4. Return to the bot.\n"
        "5. Open “My Subscription” and click “Connect VPN”.\n\n"
        "If automatic import does not work, use the backup link on the connection page."
    )

    await callback.message.edit_text(
        text,
        reply_markup=platform_download_keyboard(HAPP_DESKTOP_RELEASES_URL),
    )
    await callback.answer()


@router.callback_query(F.data == "download_vpn:installed")
async def download_vpn_installed_callback(callback: CallbackQuery):
    text = (
        "Client Installed\n\n"
        "Next:\n\n"
        "1. If you do not have a subscription yet, click “Buy VPN”.\n"
        "2. If your subscription is already active, click “My Subscription”.\n"
        "3. In the subscription section, click “Connect VPN”.\n\n"
        "The bot will open the connection page, and Happ should import the subscription automatically."
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
        "1. How do I start using the VPN?\n"
        "Install Happ from “Download VPN”, buy a subscription, then open “My Subscription” "
        "and click “Connect VPN”.\n\n"
        "2. Where can I get access after payment?\n"
        "In “My Subscription”. You will see a “Connect VPN” button there.\n\n"
        "3. Do I need to copy the VLESS key manually?\n"
        "Usually not. The bot provides a connection page through which Happ should import "
        "the subscription automatically.\n\n"
        "4. What should I do if Happ did not open automatically?\n"
        "On the connection page, click “Open Manually”. If that does not help, copy the backup "
        "link and add it to Happ as a subscription.\n\n"
        "5. What should I do if I paid but access did not appear?\n"
        "Open the order message and click “Check Payment”. If the payment is still not found, "
        "contact support and send the Order ID, txid, amount, and network.\n\n"
        "6. What if I sent the wrong amount or used the wrong network?\n"
        "Automatic activation may fail. This payment will require manual review.\n\n"
        "7. How do I renew my subscription?\n"
        "Open “My Subscription” and click “Renew Subscription”. After payment, the new period will be added "
        "to your current active subscription.\n\n"
        "8. What happens after the subscription expires?\n"
        "Access will stop working. Renew the subscription to restore it."
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
        f"Support contact: @{support_username.lstrip('@')}"
        if support_username
        else "The support contact has not been configured yet."
    )

    text = (
        "Support\n\n"
        "Choose the type of problem:\n\n"
        "• Payment Problem\n"
        "• VPN Does Not Connect\n\n"
        f"{contact_text}\n\n"
        "Before contacting support, prepare the Order ID, txid, payment amount, network, and a screenshot of the error."
    )

    await callback.message.edit_text(
        text,
        reply_markup=support_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "support:payment")
async def support_payment_callback(callback: CallbackQuery):
    text = (
        "Payment Problem\n\n"
        "Before contacting support, prepare:\n\n"
        "1. Order ID.\n"
        "2. Transaction txid.\n"
        "3. Payment amount.\n"
        "4. Currency and network, for example USDT / TRC20.\n"
        "5. Screenshot from the wallet or exchange.\n\n"
        "Common reasons:\n"
        "• the exact amount was not sent;\n"
        "• the wrong network was selected;\n"
        "• the transaction has not been confirmed yet;\n"
        "• the order has already expired."
    )

    await callback.message.edit_text(
        text,
        reply_markup=support_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "support:vpn")
async def support_vpn_callback(callback: CallbackQuery):
    text = (
        "VPN Does Not Connect\n\n"
        "Check the following:\n\n"
        "1. The subscription is active in “My Subscription”.\n"
        "2. Happ is installed.\n"
        "3. You clicked “Connect VPN” from the bot.\n"
        "4. You clicked “Open Manually” on the connection page if automatic opening did not work.\n"
        "5. If it does not work over Wi-Fi, try mobile data.\n\n"
        "For support, prepare:\n"
        "• device model;\n"
        "• Android / iOS / Windows / macOS;\n"
        "• screenshot of the error;\n"
        "• time of the connection attempt."
    )

    await callback.message.edit_text(
        text,
        reply_markup=support_back_keyboard(),
    )
    await callback.answer()