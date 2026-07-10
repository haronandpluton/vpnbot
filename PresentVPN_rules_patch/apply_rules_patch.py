from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PAYLOAD_DIR = SCRIPT_DIR / "payload"
PROJECT_ROOT = Path.cwd().resolve()

EXPECTED_ROOT_FILES = (
    PROJECT_ROOT / "app" / "bot" / "main.py",
    PROJECT_ROOT / "app" / "bot" / "commands.py",
    PROJECT_ROOT / "tests" / "test_bot_commands.py",
)

for expected_path in EXPECTED_ROOT_FILES:
    if not expected_path.exists():
        raise SystemExit(
            "Запусти скрипт из корня vpn_telegram_project. "
            f"Не найден файл: {expected_path}"
        )

timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_root = (
    Path(tempfile.gettempdir())
    / f"presentvpn_rules_backup_{timestamp}"
)
backup_root.mkdir(parents=True, exist_ok=False)

changed_files: list[str] = []


def backup_file(path: Path) -> None:
    relative = path.relative_to(PROJECT_ROOT)
    destination = backup_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)


def replace_once(
    relative_path: str,
    old: str,
    new: str,
    *,
    marker: str,
) -> None:
    path = PROJECT_ROOT / relative_path
    text = path.read_text(encoding="utf-8")

    if marker in text:
        return

    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"Безопасная замена остановлена: {relative_path}. "
            f"Ожидалось одно совпадение, найдено: {count}"
        )

    backup_file(path)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    changed_files.append(relative_path)


def copy_payload_file(relative_path: str) -> None:
    source = PAYLOAD_DIR / relative_path
    destination = PROJECT_ROOT / relative_path

    if not source.exists():
        raise SystemExit(f"В пакете отсутствует файл: {source}")

    source_bytes = source.read_bytes()

    if destination.exists() and destination.read_bytes() == source_bytes:
        return

    if destination.exists():
        backup_file(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source_bytes)
    changed_files.append(relative_path)


replace_once(
    "app/bot/commands.py",
    '    BotCommand(command="help", description="🆘 Поддержка"),\n',
    (
        '    BotCommand(command="help", description="🆘 Поддержка"),\n'
        '    BotCommand(command="rules", description="📄 Правила сервиса"),\n'
    ),
    marker='BotCommand(command="rules"',
)

replace_once(
    "app/bot/main.py",
    "from app.bot.handlers.info import router as info_router\n",
    (
        "from app.bot.handlers.info import router as info_router\n"
        "from app.bot.handlers.legal import router as legal_router\n"
    ),
    marker="from app.bot.handlers.legal import router as legal_router",
)

replace_once(
    "app/bot/main.py",
    "    dp.include_router(info_router)\n",
    (
        "    dp.include_router(info_router)\n"
        "    dp.include_router(legal_router)\n"
    ),
    marker="dp.include_router(legal_router)",
)

replace_once(
    "app/bot/handlers/info.py",
    '        f"{contact_text}"\n',
    (
        '        f"{contact_text}\\n\\n"\n'
        '        "Правила сервиса: /rules"\n'
    ),
    marker='"Правила сервиса: /rules"',
)

replace_once(
    "app/bot/handlers/buy.py",
    (
        '        "Срок: 30 дней\\n\\n"\n'
        '        "Выбери способ оплаты:"\n'
    ),
    (
        '        "Срок: 30 дней\\n\\n"\n'
        '        "Оплачивая подписку, ты подтверждаешь, что ознакомился "\n'
        '        "с правилами сервиса: /rules\\n\\n"\n'
        '        "Выбери способ оплаты:"\n'
    ),
    marker="с правилами сервиса: /rules",
)

replace_once(
    "tests/test_bot_commands.py",
    '        ("help", "🆘 Поддержка"),\n',
    (
        '        ("help", "🆘 Поддержка"),\n'
        '        ("rules", "📄 Правила сервиса"),\n'
    ),
    marker='("rules", "📄 Правила сервиса")',
)

replace_once(
    "tests/test_start_and_buy_handlers.py",
    (
        '    assert "Стоимость: 4 USDT" '
        'in callback.message.edit_text_calls[0]["text"]\n'
    ),
    (
        '    assert "Стоимость: 4 USDT" '
        'in callback.message.edit_text_calls[0]["text"]\n'
        '    assert "/rules" in callback.message.edit_text_calls[0]["text"]\n'
    ),
    marker='assert "/rules" in callback.message.edit_text_calls[0]["text"]',
)

router_test_path = PROJECT_ROOT / "tests/test_bot_main_and_db_middleware.py"
router_test_text = router_test_path.read_text(encoding="utf-8")

if "assert len(dispatcher.routers) == 20" not in router_test_text:
    if "assert len(dispatcher.routers) == 19" not in router_test_text:
        raise SystemExit(
            "Не найден ожидаемый production router count в "
            "tests/test_bot_main_and_db_middleware.py"
        )

    backup_file(router_test_path)
    router_test_text = router_test_text.replace(
        "assert len(dispatcher.routers) == 19",
        "assert len(dispatcher.routers) == 20",
        1,
    )
    changed_files.append("tests/test_bot_main_and_db_middleware.py")

if "assert len(dispatcher.routers) == 23" not in router_test_text:
    if "assert len(dispatcher.routers) == 22" not in router_test_text:
        raise SystemExit(
            "Не найден ожидаемый dev router count в "
            "tests/test_bot_main_and_db_middleware.py"
        )

    if not (backup_root / "tests/test_bot_main_and_db_middleware.py").exists():
        backup_file(router_test_path)

    router_test_text = router_test_text.replace(
        "assert len(dispatcher.routers) == 22",
        "assert len(dispatcher.routers) == 23",
        1,
    )

    if "tests/test_bot_main_and_db_middleware.py" not in changed_files:
        changed_files.append("tests/test_bot_main_and_db_middleware.py")

router_test_path.write_text(router_test_text, encoding="utf-8")

for relative_path in (
    "app/bot/handlers/legal.py",
    "app/legal/__init__.py",
    "app/legal/terms.txt",
    "app/legal/privacy.txt",
    "app/legal/refund_policy.txt",
    "tests/test_legal_handlers.py",
):
    copy_payload_file(relative_path)

print("RULES_PATCH_APPLIED")
print(f"BACKUP={backup_root}")

if changed_files:
    print("CHANGED_FILES:")
    for changed_file in changed_files:
        print(f"  {changed_file}")
else:
    print("Изменения уже были применены ранее.")
