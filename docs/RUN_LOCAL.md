# Локальный запуск проекта

## 1. Создать `.env`

Скопируй файл:

```text
.env.example
```

в новый файл:

```text
.env
```

И укажи локальные значения:

```env
BOT_TOKEN=your_dev_bot_token
ADMINS=your_telegram_id
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/vpn_bot
LOG_LEVEL=INFO
DEV_MODE=true
```

Важно:

- `BOT_TOKEN` — токен тестового или текущего Telegram-бота.
- `ADMINS` — Telegram ID администратора.
- `DATABASE_URL` — строка подключения к локальной PostgreSQL.
- `DEV_MODE=true` — включает dev/test-команды для локальной разработки.

---

## 2. Запустить PostgreSQL

Если используется Docker Compose:

```bash
docker compose up -d
```

Если PostgreSQL уже запущен отдельным контейнером, проверь, что он доступен по адресу из `.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/vpn_bot
```

---

## 3. Проверить зависимости

Активируй виртуальное окружение:

```powershell
.venv\Scripts\activate
```

Установи зависимости, если они еще не установлены:

```bash
pip install -r requirements.txt
```

---

## 4. Применить миграции

Перед запуском бота база должна быть приведена к актуальной структуре:

```bash
alembic upgrade head
```

Если миграции уже применены, команда просто подтвердит актуальное состояние.

---

## 5. Запустить бота

Из корня проекта:

```bash
python -m app.bot.main
```

Ожидаемо в логах будет запуск polling:

```text
Start polling
```

Если `DEV_MODE=true`, в логах должно быть:

```text
DEV_MODE=true: dev/test-роутеры загружены
```

Если `DEV_MODE=false`, в логах должно быть:

```text
DEV_MODE=false: dev/test-роутеры не загружены
```

---

## 6. Проверить базовые пользовательские команды

В Telegram:

```text
/start
```

Проверяет запуск бота.

```text
/buy
```

Проверяет создание заказа.

```text
/my_subscription
```

Проверяет просмотр активной подписки пользователя.

---

## 7. Проверить админ-панель

В Telegram от имени администратора:

```text
/admin
```

Проверяет главное меню администратора.

Дополнительно:

```text
/admin_commands
/admin_actions
/admin_active_subscriptions
/admin_invalid_payments
```

---

## 8. Проверить dev-режим

При локальной разработке в `.env` должно быть:

```env
DEV_MODE=true
```

После перезапуска бота команда должна работать:

```text
/dev_create_active_subscription
```

Она создает тестовую активную подписку.

После этого можно проверить:

```text
/my_subscription
```

---

## 9. Проверить production-режим локально

Поставь в `.env`:

```env
DEV_MODE=false
```

Перезапусти бота:

```powershell
taskkill /F /IM python.exe
.venv\Scripts\activate
python -m app.bot.main
```

После этого dev/test-роутеры не должны загружаться.

Команда:

```text
/dev_create_active_subscription
```

не должна выполнять создание подписки.

---

## 10. Вернуть режим разработки

После проверки production-режима для дальнейшей разработки верни:

```env
DEV_MODE=true
```

И снова перезапусти бота:

```bash
python -m app.bot.main
```

---

## 11. Частые проблемы

### Telegram Unauthorized

Ошибка:

```text
TelegramUnauthorizedError: Telegram server says - Unauthorized
```

Причина: неверный `BOT_TOKEN`.

Проверить:

- токен скопирован полностью;
- нет лишних пробелов;
- токен взят у BotFather;
- используется токен нужного бота.

---

### ConnectionRefusedError / WinError 1225

Ошибка:

```text
ConnectionRefusedError: [WinError 1225]
```

Причина: бот не может подключиться к PostgreSQL.

Проверить:

- PostgreSQL запущен;
- Docker-контейнер работает;
- порт базы доступен;
- `DATABASE_URL` в `.env` указан корректно;
- база `vpn_bot` существует.

---

### Dev-команды отключены

Сообщение:

```text
Dev-команды отключены.
```

Причина: в `.env` стоит:

```env
DEV_MODE=false
```

Для локальной разработки нужно:

```env
DEV_MODE=true
```

После изменения `.env` обязательно перезапустить бота.

---

## 12. Правило для production

На сервере должно быть:

```env
DEV_MODE=false
```

Это отключает dev/test-роутеры и защищает проект от случайного создания тестовых заказов, платежей и подписок.