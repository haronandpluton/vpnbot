from app.config.settings import get_settings


def is_admin(telegram_id: int) -> bool:
    settings = get_settings()
    return telegram_id in settings.admin_ids


def is_dev_mode_enabled() -> bool:
    settings = get_settings()
    return settings.dev_mode


def can_use_dev_commands(telegram_id: int) -> bool:
    return is_admin(telegram_id) and is_dev_mode_enabled()