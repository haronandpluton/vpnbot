from __future__ import annotations

from pathlib import Path

from app.config.settings import Settings


ENV_EXAMPLE = Path(".env.example")
RUN_LOCAL_DOC = Path("docs/RUN_LOCAL.md")
PRODUCTION_DOC = Path("docs/PRODUCTION_READINESS.md")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def env_example_keys() -> set[str]:
    keys: set[str] = set()

    for raw_line in read(ENV_EXAMPLE).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _ = line.split("=", 1)
        keys.add(key.strip())

    return keys


def settings_aliases() -> set[str]:
    aliases: set[str] = set()

    for field in Settings.model_fields.values():
        if field.alias:
            aliases.add(field.alias)

    return aliases


def test_env_example_uses_admin_ids_alias_that_settings_reads():
    content = read(ENV_EXAMPLE)

    assert "ADMIN_IDS=" in content
    assert "Example: ADMIN_IDS=" in content
    assert "ADMINS=" not in content
    assert "Example: ADMINS=" not in content


def test_docs_use_admin_ids_alias_that_settings_reads():
    for path in [RUN_LOCAL_DOC, PRODUCTION_DOC]:
        content = read(path)

        assert "ADMIN_IDS" in content
        assert "ADMINS" not in content


def test_env_example_has_required_runtime_aliases():
    keys = env_example_keys()

    assert "BOT_TOKEN" in keys
    assert "ADMIN_IDS" in keys
    assert "DATABASE_URL" in keys
    assert "LOG_LEVEL" in keys
    assert "DEV_MODE" in keys


def test_env_example_does_not_document_unknown_admin_alias():
    keys = env_example_keys()

    assert "ADMINS" not in keys


def test_env_example_keys_are_known_by_settings_or_explicitly_supported_comments_only():
    keys = env_example_keys()
    aliases = settings_aliases()
    accepted_field_env_names = {field_name.upper() for field_name in Settings.model_fields}

    unknown_keys = keys - aliases - accepted_field_env_names

    assert unknown_keys == set()


def test_env_example_keeps_production_safe_dev_mode_default():
    content = read(ENV_EXAMPLE)

    assert "DEV_MODE=false" in content
    assert "DEV_MODE=true" not in content


def test_production_docs_warn_about_dev_mode_false_and_migrations():
    content = read(PRODUCTION_DOC)

    assert "DEV_MODE=false" in content
    assert "Alembic-миграции применены" in content
    assert "Dev/test-роутеры не загружаются" in content


def test_run_local_docs_contain_core_local_commands():
    content = read(RUN_LOCAL_DOC)

    assert "alembic upgrade head" in content
    assert "python -m app.bot.main" in content
    assert "/start" in content
    assert "/admin" in content
    assert "/dev_create_active_subscription" in content