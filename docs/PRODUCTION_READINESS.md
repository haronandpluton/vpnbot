# Готовность к production

## Текущая версия проекта

v3.0 — Подготовка проекта к production-режиму

## Подтвержденный runtime-flow

```text
mock adapter
→ normalized transaction
→ polling processor
→ matching order
→ payment_event
→ payment confirmed
→ order activated
→ subscription active
→ vless config generated
```

## Реализованные основные модули

- Стартовый пользовательский сценарий
- Сценарий покупки и создания заказа
- Payment Polling MVP
- Обработка payment events
- Подтверждение платежа
- Обработка некорректных платежей
- Активация подписки
- Генерация VLESS-конфига
- Просмотр подписки пользователем
- Админ-панель
- Просмотр заказа администратором
- Просмотр платежа администратором
- Просмотр подписки администратором
- Просмотр пользователя администратором
- Список активных подписок
- Список некорректных платежей
- Повторная отправка VPN-конфига
- Ручное продление подписки
- Ручное отключение подписки
- Журнал действий администратора
- Список команд в админке
- Защита dev/test-команд
- Отключение dev-роутеров в production-режиме

## Production-безопасность

Dev/test-команды защищены двумя слоями:

1. `DevCommandsGuardMiddleware`
2. Условное подключение dev-роутеров через `DEV_MODE`

Когда `DEV_MODE=false`:

```text
dev/test-роутеры не загружаются
dev/test-команды блокируются
```

Когда `DEV_MODE=true`:

```text
dev/test-роутеры загружаются
dev/test-команды доступны только администраторам
```

## Обязательные значения `.env` для production

```env
BOT_TOKEN=real_bot_token
ADMINS=real_admin_telegram_id
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/db_name
LOG_LEVEL=INFO
DEV_MODE=false
```

## Значения `.env` для локальной разработки

```env
BOT_TOKEN=dev_bot_token
ADMINS=your_telegram_id
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/vpn_bot
LOG_LEVEL=INFO
DEV_MODE=true
```

## Чеклист перед deployment

Перед размещением на сервере:

- `.env` существует на сервере
- `.env` не попал в Git
- `.env.example` не содержит настоящих секретов
- `DEV_MODE=false`
- `BOT_TOKEN` настоящий и валидный
- `ADMINS` содержит корректные Telegram ID администраторов
- PostgreSQL доступен
- Alembic-миграции применены
- Бот запускается командой `python -m app.bot.main`
- Dev/test-роутеры не загружаются
- `/admin` работает для администратора
- `/start` работает для пользователя
- `/my_subscription` работает для пользователя