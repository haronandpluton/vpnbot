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
        "Нажми «Подключить VPN», затем открой страницу подключения. "
        "Happ VPN должен открыться автоматически и импортировать подписку."
    )



def format_expired_vpn_subscription_text(
    *,
    device_limit: int | None,
    expires_at,
) -> str:
    expires_at_text = format_datetime(expires_at)

    return (
        "Срок VPN-подписки истёк.\n\n"
        f"Устройств: {device_limit or '—'}\n"
        f"Была активна до: {expires_at_text}\n\n"
        "Нажми «Продлить подписку», чтобы возобновить доступ "
        "с тем же VPN-ключом."
    )


def format_vpn_config_text(config_uri: str) -> str:
    return (
        "Страница подключения VPN:\n\n"
        "Нажми кнопку ниже — откроется страница подключения, после чего Happ VPN "
        "должен открыться автоматически и импортировать подписку.\n\n"
        "Если автоматическое открытие не сработало, на странице будет кнопка "
        "«Открыть вручную» и резервная кнопка «Копировать».\n\n"
        "Резервная ссылка:\n"
        f"<code>{config_uri}</code>"
    )


def happ_android_instruction_text() -> str:
    return (
        "Подключение через Happ VPN на Android:\n\n"
        "1. Установи Happ VPN.\n"
        "2. Нажми «Подключить VPN» в этом боте.\n"
        "3. Нажми «Открыть в Happ VPN».\n"
        "4. Подтверди открытие приложения, если Android спросит разрешение.\n"
        "5. Happ VPN импортирует подписку.\n"
        "6. Выбери добавленный профиль и включи VPN."
    )


def happ_ios_instruction_text() -> str:
    return (
        "Подключение на iPhone:\n\n"
        "1. Установи Happ VPN или другой клиент с поддержкой VLESS-подписок.\n"
        "2. Нажми «Подключить VPN» в этом боте.\n"
        "3. Открой страницу подключения.\n"
        "4. Если автоматический импорт не сработает, скопируй ссылку на странице "
        "и добавь её в приложении как Subscription / Подписку."
    )


def happ_fallback_text() -> str:
    return (
        "Если Happ VPN не открылся автоматически:\n\n"
        "1. Нажми «Подключить VPN».\n"
        "2. На странице подключения нажми «Открыть вручную».\n"
        "3. Если и это не сработало — нажми «Копировать».\n"
        "4. Открой Happ VPN вручную.\n"
        "5. Нажми + и выбери «Импорт/Вставить из буфера» или Subscription / URL.\n\n"
        "Основной рабочий формат подключения уже подготовлен на странице автоматически."
    )
