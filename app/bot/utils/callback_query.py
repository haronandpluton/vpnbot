from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message


async def edit_callback_message(
    message: Message,
    text: str,
    **kwargs,
) -> None:
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
