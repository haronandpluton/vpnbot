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
ADMIN_IDS=real_admin_telegram_id
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/db_name
LOG_LEVEL=INFO
DEV_MODE=false
```

## Значения `.env` для локальной разработки

```env
BOT_TOKEN=dev_bot_token
ADMIN_IDS=your_telegram_id
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
- `ADMIN_IDS` содержит корректные Telegram ID администраторов
- PostgreSQL доступен
- Alembic-миграции применены
- Бот запускается командой `python -m app.bot.main`
- Dev/test-роутеры не загружаются
- `/admin` работает для администратора
- `/start` работает для пользователя
- `/my_subscription` работает для пользователя
## Надёжная синхронизация ZA subscription metadata

Рабочий поток после изменения подписки:

```text
commit платежа/подписки
→ немедленная попытка полного metadata snapshot
→ атомарная загрузка во временный файл на ZA
→ проверка JSON
→ atomic mv в subscriptions_meta.json
→ при ошибке: один unresolved system_errors marker
→ фоновый retry scheduler
→ после успешного snapshot все старые sync markers закрываются
```

Обязательные production-настройки:

```env
VPN_SUBSCRIPTION_PUBLIC_BASE_URL=https://connect.presentvpn.click
SUBSCRIPTION_META_OUTPUT_PATH=deploy/vpn-subscription/subscriptions_meta.generated.json
SUBSCRIPTION_META_REMOTE_TARGET=vpnadmin@139.84.251.197:/opt/vpn-subscription/subscriptions_meta.json
SUBSCRIPTION_META_SSH_KEY=C:/Users/User/.ssh/presentvpn_za_admin
SUBSCRIPTION_META_SYNC_TIMEOUT_SECONDS=60
SUBSCRIPTION_META_RETRY_SCHEDULER_ENABLED=true
SUBSCRIPTION_META_RETRY_INTERVAL_SECONDS=120
SUBSCRIPTION_META_RETRY_INITIAL_DELAY_SECONDS=60
```

Сбой SSH/SCP не откатывает уже подтверждённый платёж, статус заказа или подписку. Ошибка фиксируется как `subscription_meta_sync_failed` в `system_errors` и повторяется отдельным scheduler-процессом внутри бота.

Проверки после запуска:

- в логах есть `Subscription metadata retry scheduler started`;
- не создаются новые дубли `subscription_meta_sync_failed` при каждом retry;
- `retry_count` увеличивается у существующей unresolved-записи;
- после успешной синхронизации запись получает `is_resolved=true` и `resolved_at`;
- рабочий JSON на ZA заменяется только после успешной серверной валидации.
