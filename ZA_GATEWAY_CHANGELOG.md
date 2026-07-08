# ZA gateway patch

## Причина изменений

Старая реализация смешивала два разных адреса:

- публичный connect/subscription gateway;
- европейскую VPN-ноду, куда должен идти VLESS-трафик.

Также любой синтаксически корректный UUID принимался как разрешённый, а Python-сервис
сам завершал TLS на публичном `:2097` с устаревшими путями сертификата.

## Что изменено

1. Публичные ссылки бота используют `https://connect.presentvpn.click`.
2. VLESS-профиль продолжает указывать на отдельно настраиваемую EU VPN-ноду.
3. UUID разрешён только при наличии в `subscriptions_meta.json`.
4. Неизвестный UUID получает `403 Forbidden`.
5. Python-сервис слушает только `127.0.0.1:2097` по HTTP.
6. TLS завершает Nginx на `443`.
7. Добавлен `/healthz`.
8. При частично записанном metadata-файле сохраняется последняя валидная версия.
9. Добавлены systemd unit, Nginx-конфигурация и env-шаблон.
10. Удалены старые hardcoded connect URL из `vpn_access_service.py`.
11. PowerShell sync больше не содержит старый IP/root target и читает `.env`.

## Важная локальная настройка

В рабочем `.env` backend нужно заменить старый target:

```dotenv
VPN_SUBSCRIPTION_PUBLIC_BASE_URL=https://connect.presentvpn.click
SUBSCRIPTION_META_REMOTE_TARGET=vpnadmin@139.84.251.197:/opt/vpn-subscription/subscriptions_meta.json
SUBSCRIPTION_META_SSH_KEY=C:\Users\User\.ssh\presentvpn_za_admin
```

Сам `.env` в архив намеренно не включён.

## Проверка

В тестовой среде выполнено:

```text
ruff: All checks passed
pytest: 666 passed
```

Также выполнен smoke test локального HTTP-сервиса:

```text
GET /healthz -> 200
GET /<known_uuid> -> 200 и VLESS EU-ноды
GET /<unknown_uuid> -> 403
```
