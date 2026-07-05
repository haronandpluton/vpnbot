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
from app.bot.keyboards.vpn_access import vpn_access_keyboard
from app.bot.texts.vpn_access import (
    format_datetime,
    format_vpn_access_text,
    format_vpn_config_text,
    happ_android_instruction_text,
    happ_fallback_text,
    happ_ios_instruction_text,
)


def row_texts(markup):
    return [[button.text for button in row] for row in markup.inline_keyboard]


def row_callbacks(markup):
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


def row_urls(markup):
    return [[button.url for button in row] for row in markup.inline_keyboard]


def test_format_datetime_handles_none_and_formats_without_timezone_suffix():
    value = datetime(2026, 7, 5, 12, 34, tzinfo=timezone.utc)

    assert format_datetime(None) == "не указано"
    assert format_datetime(value) == "05.07.2026 12:34"


def test_format_vpn_access_text_contains_device_limit_expiry_and_happ_instruction():
    expires_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

    text = format_vpn_access_text(device_limit=3, expires_at=expires_at)

    assert "Твоя VPN-подписка активна." in text
    assert "Устройств: 3" in text
    assert "Активна до: 01.08.2026 12:00" in text
    assert "Happ VPN" in text
    assert "Подключить VPN" in text


def test_format_vpn_access_text_uses_dash_for_missing_device_limit_and_missing_expiry():
    text = format_vpn_access_text(device_limit=None, expires_at=None)

    assert "Устройств: —" in text
    assert "Активна до: не указано" in text


def test_format_vpn_config_text_contains_config_uri_in_html_code_block_and_fallback_instructions():
    text = format_vpn_config_text("https://connect.example/sub-uuid")

    assert "Страница подключения VPN:" in text
    assert "Открыть вручную" in text
    assert "Копировать" in text
    assert "<code>https://connect.example/sub-uuid</code>" in text


def test_happ_android_instruction_text_contains_ordered_android_steps():
    text = happ_android_instruction_text()

    assert "Подключение через Happ VPN на Android:" in text
    assert "1. Установи Happ VPN." in text
    assert "6. Выбери добавленный профиль и включи VPN." in text


def test_happ_ios_instruction_text_contains_ios_subscription_fallback():
    text = happ_ios_instruction_text()

    assert "Подключение на iPhone:" in text
    assert "Subscription / Подписку" in text
    assert "автоматический импорт" in text


def test_happ_fallback_text_contains_manual_open_and_clipboard_flow():
    text = happ_fallback_text()

    assert "Если Happ VPN не открылся автоматически:" in text
    assert "Открыть вручную" in text
    assert "Копировать" in text
    assert "Вставить из буфера" in text


def test_main_menu_keyboard_has_stable_user_actions():
    markup = main_menu_keyboard()

    assert row_texts(markup) == [
        ["Купить VPN"],
        ["Моя подписка"],
        ["Скачать VPN"],
        ["FAQ", "Поддержка"],
    ]
    assert row_callbacks(markup) == [
        ["buy_vpn"],
        ["my_subscription"],
        ["download_vpn"],
        ["faq", "support"],
    ]


def test_tariff_keyboard_exposes_current_tariff_callbacks_and_back_button():
    markup = tariff_keyboard()

    assert row_texts(markup) == [
        ["1 устройство — 4 USDT"],
        ["2 устройства — скоро"],
        ["3 устройства — скоро"],
        ["Назад"],
    ]
    assert row_callbacks(markup) == [
        ["select_tariff:devices_1"],
        ["select_tariff:devices_2"],
        ["select_tariff:devices_3"],
        ["back_to_main_menu"],
    ]


def test_payment_method_keyboard_uses_selected_tariff_in_callback():
    markup = payment_method_keyboard("devices_1")

    assert row_texts(markup) == [["CryptoBot — 4 USDT"], ["Назад"]]
    assert row_callbacks(markup) == [
        ["select_payment:devices_1:cryptobot_usdt"],
        ["buy_vpn"],
    ]


def test_back_to_main_menu_keyboard_returns_single_stable_callback():
    markup = back_to_main_menu_keyboard()

    assert row_texts(markup) == [["Назад в меню"]]
    assert row_callbacks(markup) == [["back_to_main_menu"]]


def test_payment_check_keyboard_without_payment_url_shows_check_and_dev_button():
    markup = payment_check_keyboard(
        order_id=23,
        payment_url=None,
        show_dev_button=True,
    )

    assert row_texts(markup) == [
        ["Я оплатил / Проверить оплату"],
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
        payment_url_text="Оплатить CryptoBot",
        show_dev_button=False,
    )

    assert row_texts(markup) == [
        ["Оплатить CryptoBot"],
        ["Я оплатил / Проверить оплату"],
    ]
    assert row_callbacks(markup) == [[None], ["check_payment:23"]]
    assert row_urls(markup) == [["https://pay.example/invoice"], [None]]


def test_vpn_access_keyboard_keeps_config_resend_extend_and_instruction_callbacks():
    markup = vpn_access_keyboard()

    assert row_texts(markup) == [
        ["Подключить VPN"],
        ["Отправить доступ снова"],
        ["Продлить подписку"],
        ["Happ VPN: Android", "Happ VPN: iPhone"],
        ["Если Happ не открывается"],
    ]
    assert row_callbacks(markup) == [
        ["vpn_access:show_config"],
        ["vpn_access:show_config"],
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