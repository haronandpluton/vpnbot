# Subscription metadata retry — изменения

## Причина

Немедленная синхронизация после изменения подписки уже была best-effort и не откатывала бизнес-транзакцию, но оставались четыре риска:

1. in-app Python sync загружал рабочий JSON напрямую, без атомарной публикации;
2. при повторных сбоях могли накапливаться дубли `system_errors`;
3. не было фонового retry после восстановления SSH/ZA-сервера;
4. параллельные snapshot могли завершиться в обратном порядке и оставить устаревший файл.

## Исправлено

- process-wide serialization metadata snapshot;
- локальная атомарная запись JSON;
- upload во временный файл на ZA;
- серверная проверка `python3 -m json.tool`;
- `chmod 0660` и atomic `mv`;
- fail-closed при пустом `SUBSCRIPTION_META_REMOTE_TARGET`;
- один unresolved `subscription_meta_sync_failed` вместо дублей;
- увеличение `retry_count` при повторных ошибках;
- `resolved_at` после успешной синхронизации;
- отдельный `SubscriptionMetaRetryScheduler`;
- корректное завершение всех scheduler tasks в `app.bot.main`;
- тест, подтверждающий: сбой metadata sync не откатывает оплаченную подписку.

## Схема

```text
payment event
→ payment confirmed
→ order paid
→ subscription create/extend
→ commit
→ immediate atomic metadata sync
   ├─ success → resolve pending sync errors
   └─ failure → upsert one system_errors marker
                    ↓
              background retry
                    ↓
              success → resolve marker
```

## Миграция БД

Не требуется. Используются существующие поля таблицы `system_errors`:

- `retry_count`;
- `is_resolved`;
- `resolved_at`.
