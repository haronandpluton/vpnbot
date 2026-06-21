from __future__ import annotations

import html
import json

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.utils.access import is_admin
from app.services.admin_action_log_service import AdminActionLogService
from app.services.subscription_meta_sync_service import SubscriptionMetaSyncService

router = Router()


@router.message(Command("admin_sync_subscriptions"))
async def admin_sync_subscriptions_command(
    message: Message,
    session: AsyncSession,
) -> None:
    if message.from_user is None:
        return

    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    status_message = await message.answer(
        "Синхронизирую metadata подписок с VPS..."
    )

    try:
        result = await SubscriptionMetaSyncService(session).sync()
    except Exception as error:
        await session.rollback()

        await AdminActionLogService(session).create_action_by_admin_telegram_id(
            admin_telegram_id=message.from_user.id,
            action_type="sync_subscriptions_meta_failed",
            reason=str(error)[:500],
            payload=json.dumps(
                {
                    "error": str(error),
                },
                ensure_ascii=False,
            ),
        )

        await status_message.edit_text(
            "<b>Ошибка синхронизации subscriptions_meta.json</b>\n\n"
            f"<code>{html.escape(str(error))}</code>\n\n"
            "Проверь SSH-ключ, путь до scp и доступ к VPS.",
            parse_mode="HTML",
        )
        return

    await AdminActionLogService(session).create_action_by_admin_telegram_id(
        admin_telegram_id=message.from_user.id,
        action_type="sync_subscriptions_meta",
        reason="Manual admin metadata sync.",
        payload=json.dumps(
            {
                "exported_count": result.exported_count,
                "skipped_count": result.skipped_count,
                "output_path": result.output_path,
                "remote_target": result.remote_target,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            ensure_ascii=False,
        ),
    )

    await status_message.edit_text(
        "<b>Metadata подписок синхронизирована</b>\n\n"
        f"Экспортировано: <b>{result.exported_count}</b>\n"
        f"Пропущено: <b>{result.skipped_count}</b>\n"
        f"Файл: <code>{html.escape(result.output_path)}</code>\n"
        f"VPS: <code>{html.escape(result.remote_target)}</code>",
        parse_mode="HTML",
    )