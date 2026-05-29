def format_datetime(value) -> str:
    if value is None:
        return "не указано"

    return value.strftime("%d.%m.%Y %H:%M")


def format_vpn_access_text(
    *,
    device_limit: int | None,
    expires_at,
) -> str:
    expires_at_text = format_datetime(expires_at)

    return (
        "Твоя VPN-подписка активна.\n\n"
        f"Устройств: {device_limit or '—'}\n"
        f"Активна до: {expires_at_text}\n\n"
        "Для подключения используй Happ VPN.\n\n"
        "Нажми «Показать ключ», скопируй VLESS-ссылку и импортируй ее в Happ VPN."
    )


def format_vpn_config_text(config_uri: str) -> str:
    return (
        "Ключ для подключения:\n\n"
        f"<code>{config_uri}</code>\n\n"
        "Скопируй ключ целиком, начиная с <code>vless://</code>, "
        "и импортируй его в Happ VPN."
    )


def happ_android_instruction_text() -> str:
    return (
        "Подключение через Happ VPN на Android:\n\n"
        "1. Установи Happ VPN.\n"
        "2. Нажми «Показать ключ» в этом боте.\n"
        "3. Скопируй VLESS-ключ целиком.\n"
        "4. Открой Happ VPN.\n"
        "5. Нажми добавление профиля.\n"
        "6. Выбери импорт из буфера / URL / clipboard.\n"
        "7. Подтверди добавление профиля.\n"
        "8. Включи VPN-подключение."
    )


def happ_ios_instruction_text() -> str:
    return (
        "Подключение через Happ VPN на iPhone:\n\n"
        "1. Установи Happ VPN.\n"
        "2. Нажми «Показать ключ» в этом боте.\n"
        "3. Скопируй VLESS-ключ целиком.\n"
        "4. Открой Happ VPN.\n"
        "5. Нажми добавление профиля.\n"
        "6. Выбери импорт из буфера / URL / clipboard.\n"
        "7. Разреши добавление VPN-конфигурации, если iOS попросит подтверждение.\n"
        "8. Включи VPN-подключение."
    )


def happ_fallback_text() -> str:
    return (
        "Если Happ VPN не открывается автоматически:\n\n"
        "Это нормально. Telegram-бот не может сам вставить ключ в стороннее приложение.\n\n"
        "Что делать:\n"
        "1. Нажми «Показать ключ».\n"
        "2. Скопируй весь ключ целиком.\n"
        "3. Открой Happ VPN вручную.\n"
        "4. Импортируй ключ через URL / clipboard / буфер обмена.\n\n"
        "После подключения профиль появится в Happ VPN."
    )