from __future__ import annotations

from datetime import datetime, timezone

from app.bot.keyboards.admin_menu import admin_back_keyboard, admin_main_menu_keyboard
from app.bot.keyboards.main_menu import (
    back_to_main_menu_keyboard,
    main_menu_keyboard,
    payment_method_keyboard,
    tariff_keyboard,
)
from app.bot.keyboards.payment import payment_check_keyboard
from app.bot.utils.custom_emoji import (
    GIFT_CUSTOM_EMOJI_ID,
    STAR_CUSTOM_EMOJI_ID,
)
from app.bot.keyboards.vpn_access import (
    expired_subscription_keyboard,
    vpn_access_keyboard,
)
from app.bot.texts.vpn_access import (
    format_datetime,
    format_vpn_access_text,
    format_vpn_config_text,
    happ_android_instruction_text,
    happ_fallback_text,
    happ_ios_instruction_text,
    format_expired_vpn_subscription_text,
)


def row_texts(markup):
    return [[button.text for button in row] for row in markup.inline_keyboard]


def row_callbacks(markup):
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


def row_urls(markup):
    return [[button.url for button in row] for row in markup.inline_keyboard]


def test_format_datetime_handles_none_and_formats_without_timezone_suffix():
    value = datetime(2026, 7, 5, 12, 34, tzinfo=timezone.utc)

    assert format_datetime(None) == "not specified"
    assert format_datetime(value) == "05.07.2026 12:34"


def test_format_vpn_access_text_contains_device_limit_expiry_and_happ_instruction():
    expires_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

    text = format_vpn_access_text(device_limit=3, expires_at=expires_at)

    assert "Your VPN subscription is active." in text
    assert "Devices: 3" in text
    assert "Active until: 01.08.2026 12:00" in text
    assert "Happ VPN" in text
    assert "Connect VPN" in text


def test_format_vpn_access_text_uses_dash_for_missing_device_limit_and_missing_expiry():
    text = format_vpn_access_text(device_limit=None, expires_at=None)

    assert "Devices: —" in text
    assert "Active until: not specified" in text


def test_format_vpn_config_text_contains_config_uri_in_html_code_block_and_fallback_instructions():
    text = format_vpn_config_text("https://connect.example/sub-uuid")

    assert "VPN connection page:" in text
    assert "Open Manually" in text
    assert "Copy" in text
    assert "<code>https://connect.example/sub-uuid</code>" in text


def test_happ_android_instruction_text_contains_ordered_android_steps():
    text = happ_android_instruction_text()

    assert "Connecting through Happ VPN on Android:" in text
    assert "1. Install Happ VPN." in text
    assert "6. Select the added profile and enable the VPN." in text


def test_happ_ios_instruction_text_contains_ios_subscription_fallback():
    text = happ_ios_instruction_text()

    assert "Connecting on iPhone:" in text
    assert "Subscription / URL" in text
    assert "automatic import" in text


def test_happ_fallback_text_contains_manual_open_and_clipboard_flow():
    text = happ_fallback_text()

    assert "If Happ VPN did not open automatically:" in text
    assert "Open Manually" in text
    assert "Copy" in text
    assert "Paste from Clipboard" in text


def test_main_menu_keyboard_has_stable_user_actions():
    markup = main_menu_keyboard()

    assert row_texts(markup) == [
        ["Buy VPN"],
        ["My Subscription"],
        ["Download VPN"],
        ["FAQ", "Support"],
    ]
    assert row_callbacks(markup) == [
        ["buy_vpn"],
        ["my_subscription"],
        ["download_vpn"],
        ["faq", "support"],
    ]

def test_main_menu_keyboard_shows_trial_action_for_eligible_user():
    markup = main_menu_keyboard(trial_eligible=True)

    assert row_texts(markup) == [
        ["GET 3 VPN DAYS"],
        ["My Subscription"],
        ["Download VPN"],
        ["FAQ", "Support"],
    ]
    assert row_callbacks(markup) == [
        ["activate_trial"],
        ["my_subscription"],
        ["download_vpn"],
        ["faq", "support"],
    ]


def test_tariff_keyboard_exposes_current_tariff_callbacks_and_back_button():
    markup = tariff_keyboard()

    assert row_texts(markup) == [
        ["4$ — 33 days (30 days + 3 days)"],
        ["7,5$ — 66 days (60 days + 6 days)"],
        ["11$ — 99 days (90 days + 9 days)"],
        ["Back"],
    ]
    assert row_callbacks(markup) == [
        ["select_tariff:period_1_month"],
        ["select_tariff:period_2_months"],
        ["select_tariff:period_3_months"],
        ["back_to_main_menu"],
    ]


def test_payment_method_keyboard_uses_selected_tariff_in_callback():
    markup = payment_method_keyboard("period_2_months")

    assert row_texts(markup) == [
        ["USDT", "USDC"],
        ["BTC", "ETH"],
        ["TON", "LTC"],
        ["BNB", "TRX"],
        ["Back"],
    ]
    assert row_callbacks(markup) == [
        [
            "select_payment:period_2_months:cryptobot_usdt",
            "select_payment:period_2_months:cryptobot_usdc",
        ],
        [
            "select_payment:period_2_months:cryptobot_btc",
            "select_payment:period_2_months:cryptobot_eth",
        ],
        [
            "select_payment:period_2_months:cryptobot_ton",
            "select_payment:period_2_months:cryptobot_ltc",
        ],
        [
            "select_payment:period_2_months:cryptobot_bnb",
            "select_payment:period_2_months:cryptobot_trx",
        ],
        ["buy_vpn"],
    ]


def test_payment_method_keyboard_shows_stars_when_enabled():
    markup = payment_method_keyboard(
        "period_2_months",
        telegram_stars_enabled=True,
    )

    assert row_texts(markup) == [
        ["USDT", "USDC"],
        ["BTC", "ETH"],
        ["TON", "LTC"],
        ["BNB", "TRX"],
        ["Telegram Stars — 600 XTR"],
        ["Back"],
    ]

    assert row_callbacks(markup) == [
        [
            "select_payment:period_2_months:cryptobot_usdt",
            "select_payment:period_2_months:cryptobot_usdc",
        ],
        [
            "select_payment:period_2_months:cryptobot_btc",
            "select_payment:period_2_months:cryptobot_eth",
        ],
        [
            "select_payment:period_2_months:cryptobot_ton",
            "select_payment:period_2_months:cryptobot_ltc",
        ],
        [
            "select_payment:period_2_months:cryptobot_bnb",
            "select_payment:period_2_months:cryptobot_trx",
        ],
        ["select_stars:period_2_months"],
        ["buy_vpn"],
    ]

def test_payment_method_keyboard_uses_renew_stars_callback():
    markup = payment_method_keyboard(
        "period_3_months",
        target_subscription_id=77,
        telegram_stars_enabled=True,
    )

    assert row_texts(markup)[-2:] == [
        ["Telegram Stars — 900 XTR"],
        ["Back"],
    ]

    assert row_callbacks(markup)[-2:] == [
        ["renew_stars:77:period_3_months"],
        ["renew_subscription:77"],
    ]



def test_tariff_keyboard_uses_custom_gift_icons():
    markup = tariff_keyboard()

    tariff_buttons = [
        row[0]
        for row in markup.inline_keyboard[:-1]
    ]

    assert [
        button.icon_custom_emoji_id
        for button in tariff_buttons
    ] == [
        GIFT_CUSTOM_EMOJI_ID,
        GIFT_CUSTOM_EMOJI_ID,
        GIFT_CUSTOM_EMOJI_ID,
    ]

    assert (
        markup.inline_keyboard[-1][0].icon_custom_emoji_id
        is None
    )


def test_payment_method_keyboard_uses_custom_star_icon():
    purchase_markup = payment_method_keyboard(
        "period_2_months",
        telegram_stars_enabled=True,
    )
    renewal_markup = payment_method_keyboard(
        "period_3_months",
        target_subscription_id=77,
        telegram_stars_enabled=True,
    )

    purchase_star_button = purchase_markup.inline_keyboard[-2][0]
    renewal_star_button = renewal_markup.inline_keyboard[-2][0]

    assert (
        purchase_star_button.icon_custom_emoji_id
        == STAR_CUSTOM_EMOJI_ID
    )
    assert (
        renewal_star_button.icon_custom_emoji_id
        == STAR_CUSTOM_EMOJI_ID
    )

    assert purchase_star_button.text == (
        "Telegram Stars — 600 XTR"
    )
    assert renewal_star_button.text == (
        "Telegram Stars — 900 XTR"
    )


def test_back_to_main_menu_keyboard_returns_single_stable_callback():
    markup = back_to_main_menu_keyboard()

    assert row_texts(markup) == [["Back to Menu"]]
    assert row_callbacks(markup) == [["back_to_main_menu"]]


def test_payment_check_keyboard_without_payment_url_shows_check_and_dev_button():
    markup = payment_check_keyboard(
        order_id=23,
        payment_url=None,
        show_dev_button=True,
    )

    assert row_texts(markup) == [
        ["I Paid / Check Payment"],
        ["DEV: подтвердить mock-платёж"],
    ]
    assert row_callbacks(markup) == [
        ["check_payment:23"],
        ["dev_confirm_payment:23"],
    ]
    assert row_urls(markup) == [[None], [None]]


def test_payment_check_keyboard_with_payment_url_puts_pay_button_first_and_can_hide_dev_button():
    markup = payment_check_keyboard(
        order_id=23,
        payment_url="https://pay.example/invoice",
        payment_url_text="Pay CryptoBot",
        show_dev_button=False,
    )

    assert row_texts(markup) == [
        ["Pay CryptoBot"],
        ["I Paid / Check Payment"],
    ]
    assert row_callbacks(markup) == [[None], ["check_payment:23"]]
    assert row_urls(markup) == [["https://pay.example/invoice"], [None]]


def test_vpn_access_keyboard_binds_actions_to_selected_subscription():
    markup = vpn_access_keyboard(subscription_id=303)

    assert row_texts(markup) == [
        ["Connect VPN"],
        ["Send Access Again"],
        ["Renew Subscription"],
        ["Buy Another Subscription"],
        ["Happ VPN: Android", "Happ VPN: iPhone"],
        ["If Happ Does Not Open"],
    ]
    assert row_callbacks(markup) == [
        ["vpn_access:show_config:303"],
        ["vpn_access:show_config:303"],
        ["renew_subscription:303"],
        ["buy_vpn"],
        ["vpn_access:happ_android", "vpn_access:happ_ios"],
        ["vpn_access:happ_fallback"],
    ]


def test_admin_main_menu_keyboard_contains_recovery_dashboard_sections():
    markup = admin_main_menu_keyboard()

    assert row_texts(markup) == [
        ["Статистика"],
        ["Активные подписки"],
        ["Некорректные платежи"],
        ["Журнал действий"],
        ["Список команд"],
        ["Поиск заказа", "Поиск платежа"],
        ["Поиск подписки", "Поиск пользователя"],
        ["Обновить меню"],
    ]
    assert row_callbacks(markup) == [
        ["admin_menu:stats"],
        ["admin_menu:active_subscriptions"],
        ["admin_menu:invalid_payments"],
        ["admin_menu:actions"],
        ["admin_menu:commands_help"],
        ["admin_menu:order_lookup_help", "admin_menu:payment_lookup_help"],
        ["admin_menu:subscription_lookup_help", "admin_menu:user_lookup_help"],
        ["admin_menu:home"],
    ]


def test_admin_back_keyboard_returns_to_admin_home():
    markup = admin_back_keyboard()

    assert row_texts(markup) == [["Назад в админ-меню"]]
    assert row_callbacks(markup) == [["admin_menu:home"]]

def test_trial_vpn_access_keyboard_omits_renewal():
    markup = vpn_access_keyboard(
        subscription_id=77,
        renewable=False,
    )

    assert row_texts(markup) == [
        ["Connect VPN"],
        ["Send Access Again"],
        ["Buy VPN"],
        ["Happ VPN: Android", "Happ VPN: iPhone"],
        ["If Happ Does Not Open"],
    ]
    assert row_callbacks(markup) == [
        ["vpn_access:show_config:77"],
        ["vpn_access:show_config:77"],
        ["buy_vpn"],
        [
            "vpn_access:happ_android",
            "vpn_access:happ_ios",
        ],
        ["vpn_access:happ_fallback"],
    ]


def test_expired_trial_keyboard_routes_to_buy():
    markup = expired_subscription_keyboard(
        subscription_id=77,
        renewable=False,
    )

    assert row_texts(markup) == [["Buy VPN"]]
    assert row_callbacks(markup) == [["buy_vpn"]]


def test_expired_trial_text_offers_purchase_not_renewal():
    text = format_expired_vpn_subscription_text(
        device_limit=1,
        expires_at=datetime(
            2030,
            1,
            4,
            12,
            0,
            tzinfo=timezone.utc,
        ),
        renewable=False,
    )

    assert "Click “Buy VPN”" in text
    assert "Renew Subscription" not in text
