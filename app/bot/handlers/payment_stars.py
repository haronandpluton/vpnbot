from __future__ import annotations

import logging
import json

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from app.bot.keyboards.vpn_access import vpn_access_keyboard
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import TariffCode
from app.config.payment_options import get_payment_option
from app.config.settings import get_settings
from app.config.tariffs import (
    PURCHASABLE_TARIFF_CODES,
    TariffConfig,
    get_tariff,
)
from app.services.order_service import OrderService
from app.services.telegram_stars_payment_service import (
    TELEGRAM_STARS_CURRENCY,
    TelegramStarsConfigurationError,
    TelegramStarsPaymentService,
    TelegramStarsValidationError,
)

logger = logging.getLogger(__name__)
router = Router()


def _parse_positive_id(raw_value: str) -> int | None:
    if not raw_value.isdigit():
        return None

    value = int(raw_value)

    if value <= 0:
        return None

    return value


def _get_purchasable_tariff(raw_code: str) -> TariffConfig | None:
    try:
        tariff_code = TariffCode(raw_code)
    except ValueError:
        return None

    if tariff_code not in PURCHASABLE_TARIFF_CODES:
        return None

    return get_tariff(tariff_code)


@router.callback_query(F.data.startswith("select_stars:"))
@router.callback_query(F.data.startswith("renew_stars:"))
async def select_stars_payment_callback(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    if callback.message is None:
        await callback.answer(
            "Message is unavailable.",
            show_alert=True,
        )
        return

    callback_data = callback.data or ""
    parts = callback_data.split(":")
    target_subscription_id: int | None = None

    if callback_data.startswith("select_stars:"):
        if len(parts) != 2:
            await callback.answer(
                "Invalid payment selection.",
                show_alert=True,
            )
            return

        _, tariff_code_raw = parts

    else:
        if len(parts) != 3:
            await callback.answer(
                "Invalid payment selection.",
                show_alert=True,
            )
            return

        _, subscription_id_raw, tariff_code_raw = parts

        target_subscription_id = _parse_positive_id(
            subscription_id_raw
        )

        if target_subscription_id is None:
            await callback.answer(
                "Invalid subscription.",
                show_alert=True,
            )
            return

    tariff = _get_purchasable_tariff(tariff_code_raw)

    if tariff is None or tariff.stars_price is None:
        await callback.answer(
            "This plan is unavailable.",
            show_alert=True,
        )
        return

    payment_option = get_payment_option("telegram_stars")
    settings = get_settings()

    if (
        not payment_option.is_active
        or not settings.telegram_stars_enabled
    ):
        await callback.answer(
            "Telegram Stars payments are currently disabled.",
            show_alert=True,
        )
        return

    create_order_kwargs = {
        "telegram_id": callback.from_user.id,
        "tariff_code": tariff.code,
        "payment_option_code": payment_option.code,
        "username": callback.from_user.username,
        "first_name": callback.from_user.first_name,
        "last_name": callback.from_user.last_name,
        "language_code": callback.from_user.language_code,
    }

    if target_subscription_id is not None:
        create_order_kwargs["target_subscription_id"] = (
            target_subscription_id
        )

    try:
        order = await OrderService(session).create_order(
            **create_order_kwargs
        )

        invoice = await TelegramStarsPaymentService(
            session
        ).create_invoice(
            order_id=order.id,
            telegram_id=callback.from_user.id,
        )

    except TelegramStarsConfigurationError:
        logger.exception(
            "Telegram Stars configuration is incomplete"
        )

        await callback.answer(
            "Telegram Stars payments are temporarily unavailable.",
            show_alert=True,
        )
        return

    except TelegramStarsValidationError as error:
        await callback.answer(
            str(error),
            show_alert=True,
        )
        return

    except ValueError:
        await callback.answer(
            "Unable to create this order.",
            show_alert=True,
        )
        return

    await callback.message.answer_invoice(
        title=invoice.title,
        description=invoice.description,
        payload=invoice.payload,
        currency=TELEGRAM_STARS_CURRENCY,
        prices=[
            LabeledPrice(
                label=invoice.label,
                amount=invoice.amount,
            )
        ],
    )

    await callback.answer()


@router.pre_checkout_query()
async def telegram_stars_pre_checkout(
    query: PreCheckoutQuery,
    session: AsyncSession,
) -> None:
    decision = await TelegramStarsPaymentService(
        session
    ).validate_pre_checkout(
        telegram_id=query.from_user.id,
        invoice_payload=query.invoice_payload,
        currency=query.currency,
        total_amount=query.total_amount,
    )

    await query.answer(
        ok=decision.ok,
        error_message=decision.error_message,
    )

@router.message(F.successful_payment)
async def telegram_stars_successful_payment(
    message: Message,
    session: AsyncSession,
) -> None:
    if message.from_user is None:
        return

    successful_payment = message.successful_payment

    if successful_payment is None:
        return

    raw_payload = json.dumps(
        successful_payment.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )

    try:
        _, _, subscription, _ = (
            await TelegramStarsPaymentService(
                session
            ).process_successful_payment(
                telegram_id=message.from_user.id,
                invoice_payload=successful_payment.invoice_payload,
                currency=successful_payment.currency,
                total_amount=successful_payment.total_amount,
                telegram_payment_charge_id=(
                    successful_payment.telegram_payment_charge_id
                ),
                raw_payload=raw_payload,
            )
        )

    except (
        TelegramStarsConfigurationError,
        TelegramStarsValidationError,
    ) as error:
        logger.exception(
            "Telegram Stars payment requires manual review: "
            "telegram_id=%s charge_id=%s",
            message.from_user.id,
            successful_payment.telegram_payment_charge_id,
        )

        await message.answer(
            "Telegram confirmed your payment, but automatic "
            "activation was not completed.\n\n"
            f"Reason: {error}\n\n"
            "Do not pay again. Please contact support and provide "
            "your order details."
        )
        return

    except Exception:
        logger.exception(
            "Telegram Stars activation failed: "
            "telegram_id=%s charge_id=%s",
            message.from_user.id,
            successful_payment.telegram_payment_charge_id,
        )

        await message.answer(
            "Your payment was confirmed, but VPN access has not "
            "been activated yet.\n\n"
            "Do not pay again. Please contact support."
        )
        return

    await message.answer(
        "Payment confirmed.\n\n"
        "Your VPN subscription has been activated.",
        reply_markup=vpn_access_keyboard(subscription.id),
    )