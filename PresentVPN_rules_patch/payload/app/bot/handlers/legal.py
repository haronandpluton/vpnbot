from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

router = Router()

LEGAL_DIR = Path(__file__).resolve().parents[2] / "legal"
TELEGRAM_TEXT_LIMIT = 4096
LEGAL_CHUNK_LIMIT = 3900

RULES_MENU_TEXT = (
    "Правила сервиса:\n\n"
    "1. Пользовательское соглашение\n"
    "2. Условия возврата и отмены платежа\n"
    "3. Политика конфиденциальности\n"
    "4. Тарифы"
)


def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пользовательское соглашение",
                    callback_data="rules:terms",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Возврат и отмена платежа",
                    callback_data="rules:refund",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Политика конфиденциальности",
                    callback_data="rules:privacy",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Тарифы",
                    callback_data="rules:tariffs",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад в меню",
                    callback_data="back_to_main_menu",
                )
            ],
        ]
    )


def rules_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назад к правилам",
                    callback_data="rules",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад в меню",
                    callback_data="back_to_main_menu",
                )
            ],
        ]
    )


@lru_cache(maxsize=3)
def load_legal_text(filename: str) -> str:
    path = LEGAL_DIR / filename
    return path.read_text(encoding="utf-8").strip()


def split_telegram_text(
    text: str,
    *,
    limit: int = LEGAL_CHUNK_LIMIT,
) -> list[str]:
    if limit <= 0 or limit > TELEGRAM_TEXT_LIMIT:
        raise ValueError("Invalid Telegram chunk limit")

    normalized = text.strip()
    if not normalized:
        return []

    chunks: list[str] = []
    current = ""

    for paragraph in normalized.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        while len(paragraph) > limit:
            split_at = paragraph.rfind(" ", 0, limit + 1)
            if split_at <= 0:
                split_at = limit

            chunks.append(paragraph[:split_at].rstrip())
            paragraph = paragraph[split_at:].lstrip()

        current = paragraph

    if current:
        chunks.append(current)

    return chunks


async def send_legal_document(
    callback: CallbackQuery,
    *,
    filename: str,
) -> None:
    chunks = split_telegram_text(load_legal_text(filename))

    await callback.answer()

    for index, chunk in enumerate(chunks):
        is_last = index == len(chunks) - 1
        await callback.message.answer(
            chunk,
            reply_markup=rules_back_keyboard() if is_last else None,
        )


@router.message(Command("rules"))
async def rules_command(message: Message) -> None:
    await message.answer(
        RULES_MENU_TEXT,
        reply_markup=rules_keyboard(),
    )


@router.callback_query(F.data == "rules")
async def rules_callback(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        RULES_MENU_TEXT,
        reply_markup=rules_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "rules:terms")
async def terms_callback(callback: CallbackQuery) -> None:
    await send_legal_document(
        callback,
        filename="terms.txt",
    )


@router.callback_query(F.data == "rules:refund")
async def refund_callback(callback: CallbackQuery) -> None:
    await send_legal_document(
        callback,
        filename="refund_policy.txt",
    )


@router.callback_query(F.data == "rules:privacy")
async def privacy_callback(callback: CallbackQuery) -> None:
    await send_legal_document(
        callback,
        filename="privacy.txt",
    )


@router.callback_query(F.data == "rules:tariffs")
async def tariffs_callback(callback: CallbackQuery) -> None:
    text = (
        "Тарифы\n\n"
        "1 устройство — 4 USDT\n"
        "Срок подписки — 30 дней.\n\n"
        "Тарифы на 2 и 3 устройства будут добавлены позднее."
    )

    await callback.message.edit_text(
        text,
        reply_markup=rules_back_keyboard(),
    )
    await callback.answer()
