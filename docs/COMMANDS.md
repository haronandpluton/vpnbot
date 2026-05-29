# Команды бота

## Пользовательские команды

### /start

Запускает бота и открывает основной пользовательский сценарий.

### /buy

Создает заказ на покупку VPN-доступа.

### /my_subscription

Показывает активную VPN-подписку пользователя, дату окончания, лимит устройств и VLESS-конфиг.

### /info

Показывает информационный раздел бота, если соответствующий handler подключен.

---

## Админские команды

### /admin

Главная админ-панель.

Включает:

- Статистику
- Активные подписки
- Некорректные платежи
- Журнал действий администратора
- Список команд
- Подсказки по поиску сущностей

### /admin_stats

Показывает статистику проекта:

- Пользователи
- Заказы
- Платежи
- Подписки
- Подтвержденная выручка

### /admin_active_subscriptions

Показывает активные подписки, отсортированные по ближайшей дате окончания.

### /admin_invalid_payments

Показывает некорректные платежи:

- wrong_amount
- wrong_network
- wrong_currency

---

## Поиск сущностей

### /admin_order `<order_id>`

Показывает детальную карточку заказа:

- Order
- User
- Payments
- Events
- Subscriptions

Пример:

```text
/admin_order 49
```

### /admin_payment `<payment_id>`

Показывает детальную карточку платежа:

- Payment
- Order
- User
- Events
- Subscriptions

Пример:

```text
/admin_payment 45
```

### /admin_subscription `<subscription_id>`

Показывает детальную карточку подписки:

- Subscription
- User
- Order
- Payments
- Events

Пример:

```text
/admin_subscription 15
```

### /admin_user `<user_id>`

Показывает пользователя по внутреннему ID из базы данных.

Пример:

```text
/admin_user 46
```

### /admin_user_tg `<telegram_id>`

Показывает пользователя по Telegram ID.

Пример:

```text
/admin_user_tg 611113612212
```

---

## Ручные действия администратора

### /admin_resend_config `<order_id>`

Повторно отправляет пользователю VPN-конфиг.

Новый UUID не создается.

Пример:

```text
/admin_resend_config 72
```

### /admin_extend_subscription `<subscription_id>` `<days>`

Ручное продление подписки на указанное количество дней.

Действие записывается в журнал действий администратора.

Пример:

```text
/admin_extend_subscription 15 30
```

### /admin_disable_subscription `<subscription_id>` `<reason>`

Ручное отключение подписки с указанием причины.

Действие записывается в журнал действий администратора.

Пример:

```text
/admin_disable_subscription 17 test_cleanup
```

---

## Журнал действий администратора

### /admin_actions

Показывает последние действия администраторов.

Фиксирует, например:

- ручное продление подписки
- ручное отключение подписки
- повторную отправку VPN-конфига

### /admin_actions_subscription `<subscription_id>`

Показывает действия администраторов по конкретной подписке.

Пример:

```text
/admin_actions_subscription 17
```

### /admin_actions_user `<user_id>`

Показывает действия администраторов по конкретному пользователю.

Пример:

```text
/admin_actions_user 58
```

---

## Dev/test-команды

Dev/test-команды доступны только при:

```env
DEV_MODE=true
```

И только администраторам.

### /dev_create_active_subscription

Создает тестовую активную подписку.

Используется для локальной разработки и тестирования.

### /test_payment_check

Тестовая команда проверки платежного сценария, если handler подключен.

---

## Production-правило

На production должно быть:

```env
DEV_MODE=false
```

В этом режиме dev/test-роутеры не загружаются, а dev/test-команды недоступны.

Защита реализована двумя слоями:

1. `DevCommandsGuardMiddleware`
2. Условное подключение dev/test-роутеров через `DEV_MODE`