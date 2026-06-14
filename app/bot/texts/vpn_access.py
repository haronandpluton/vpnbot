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
        "Нажми «Показать ключ», скопируй ссылку подписки и добавь её в Happ VPN."
    )


def format_vpn_config_text(config_uri: str) -> str:
    return (
        "Ссылка подписки для подключения:\n\n"
        f"<code>{config_uri}</code>\n\n"
        "Добавь эту ссылку в Happ VPN как подписку / subscription.\n\n"
        "Если Happ VPN не добавляет ссылку автоматически:\n"
        "1. Скопируй ссылку целиком.\n"
        "2. Открой Happ VPN.\n"
        "3. Нажми добавление профиля.\n"
        "4. Выбери импорт по ссылке / URL / subscription, если такой пункт есть.\n"
        "5. Вставь ссылку и подтверди добавление."
    )


def happ_android_instruction_text() -> str:
    return (
        "Подключение через Happ VPN на Android:\n\n"
        "1. Установи Happ VPN.\n"
        "2. Нажми «Показать ключ» в этом боте.\n"
        "3. Скопируй ссылку подписки целиком.\n"
        "4. Открой Happ VPN.\n"
        "5. Нажми добавление профиля.\n"
        "6. Выбери импорт по ссылке / URL / subscription, если такой пункт есть.\n"
        "7. Вставь ссылку и подтверди добавление.\n"
        "8. Включи VPN-подключение."
    )


def happ_ios_instruction_text() -> str:
    return (
        "Подключение на iPhone:\n\n"
        "1. Установи Happ VPN или другой клиент с поддержкой VLESS-подписок.\n"
        "2. Нажми «Показать ключ» в этом боте.\n"
        "3. Скопируй ссылку подписки целиком.\n"
        "4. Добавь её в приложении как Subscription / Подписку.\n"
        "5. Обнови подписку.\n"
        "6. Выбери появившийся профиль и включи VPN."
    )


def happ_fallback_text() -> str:
    return (
        "Если Happ VPN не открывается автоматически:\n\n"
        "Это нормально. Telegram-бот не может сам вставить ссылку в стороннее приложение.\n\n"
        "Что делать:\n"
        "1. Нажми «Показать ключ».\n"
        "2. Скопируй всю ссылку целиком.\n"
        "3. Открой Happ VPN вручную.\n"
        "4. Добавь профиль через URL / subscription / ссылку.\n\n"
        "После добавления профиль появится в Happ VPN."
    )