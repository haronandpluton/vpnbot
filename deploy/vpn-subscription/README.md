# PresentVPN subscription gateway

Отдельный публичный gateway в Южной Африке для Happ-compatible выдачи подписок.
Он не является VPN-нодой и не принимает пользовательский VPN-трафик.

## Архитектура

```text
Telegram bot / EU backend
    -> создаёт UUID в 3x-ui на EU VPN-ноде
    -> сохраняет subscription в БД
    -> экспортирует subscriptions_meta.json на ZA gateway
    -> отправляет пользователю connect URL

Пользователь
    -> https://connect.presentvpn.click/connect/<uuid>
    -> Nginx :443 на ZA gateway
    -> subscription service 127.0.0.1:2097
    -> проверка UUID по subscriptions_meta.json
    -> Happ получает VLESS-профиль EU VPN-ноды
```

Разделение ролей обязательно:

```text
PUBLIC gateway: https://connect.presentvpn.click
VPN upstream:    lab83607.hostkey.in:443
```

Публичный домен не должен автоматически подставляться в VLESS-профиль.

## Endpoints

### `GET /connect/<uuid>?device=android|ios`

Страница подключения. Пытается открыть:

```text
happ://add/https://connect.presentvpn.click/<uuid>
```

### `GET /<uuid>`

Основной subscription endpoint для Happ. Возвращает base64 body с VLESS-ссылкой.

### `GET /sub/<uuid>`

Технический fallback. Основным endpoint остаётся `/<uuid>`.

### `GET /healthz`

Liveness endpoint:

```text
HTTP 200
ok
```

## Авторизация UUID

Источник разрешённых UUID:

```text
/opt/vpn-subscription/subscriptions_meta.json
```

Любой UUID, отсутствующий в этом JSON, получает `403 Forbidden`.
Просто корректный формат UUID больше не даёт доступ.

Файл содержит активные, истёкшие и отключённые подписки:

```json
{
  "62486a8e-b420-44af-8bd8-fb8cc061a93b": {
    "expire": 1784603873,
    "upload": 0,
    "download": 0,
    "total": 0
  }
}
```

При временно повреждённом JSON процесс продолжает использовать последнюю успешно
прочитанную версию. При отсутствии файла gateway работает fail-closed и не разрешает
ни одного UUID.

## Активная и истёкшая подписка

При `expire > now` возвращается VLESS-профиль EU VPN-ноды.

При `expire <= now` возвращается нерабочая локальная заглушка с названием:

```text
❌ Подписка закончилась — продлите в Telegram
```

Happ обновляет subscription URL раз в час за счёт заголовка:

```http
profile-update-interval: 1
```

## Сетевой контур

```text
Internet -> Nginx :443 -> 127.0.0.1:2097
```

Python-сервис не поднимает TLS самостоятельно и по умолчанию слушает только
`127.0.0.1`. Порт `2097` не нужно открывать в UFW.

Публично разрешены только:

```text
22/tcp  SSH
80/tcp  ACME + redirect
443/tcp HTTPS
```

## Переменные standalone gateway

Шаблон: `vpn-subscription.env.example`.

```dotenv
VPN_SUBSCRIPTION_BIND_HOST=127.0.0.1
VPN_SUBSCRIPTION_BIND_PORT=2097
VPN_SUBSCRIPTION_META_FILE=/opt/vpn-subscription/subscriptions_meta.json
VPN_SUBSCRIPTION_PUBLIC_BASE_URL=https://connect.presentvpn.click

VPN_UPSTREAM_HOST=lab83607.hostkey.in
VPN_UPSTREAM_PORT=443
VPN_UPSTREAM_WS_PATH=/ws-test
VPN_UPSTREAM_WS_HOST=lab83607.hostkey.in
VPN_UPSTREAM_SNI=lab83607.hostkey.in
```

## Файлы deployment

```text
sub_server.py
vpn-subscription.env.example
vpn-subscription.service
nginx-connect.presentvpn.click.conf
subscriptions_meta.example.json
```

## Установка на ZA gateway

Создать отдельного системного пользователя:

```bash
sudo useradd --system --home /opt/vpn-subscription \
  --shell /usr/sbin/nologin vpnsubscription
sudo install -d -o root -g vpnsubscription -m 2770 /opt/vpn-subscription
sudo usermod -aG vpnsubscription vpnadmin
```

Скопировать файлы:

```bash
sudo install -o root -g vpnsubscription -m 0750 \
  sub_server.py /opt/vpn-subscription/sub_server.py
sudo install -o root -g vpnsubscription -m 0640 \
  subscriptions_meta.example.json \
  /opt/vpn-subscription/subscriptions_meta.json
sudo install -o root -g root -m 0600 \
  vpn-subscription.env.example /etc/vpn-subscription.env
sudo install -o root -g root -m 0644 \
  vpn-subscription.service /etc/systemd/system/vpn-subscription.service
```

После изменения групп переподключиться по SSH, затем проверить запись metadata:

```bash
id vpnadmin
ls -l /opt/vpn-subscription/subscriptions_meta.json
```

Запустить сервис:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vpn-subscription
sudo systemctl status vpn-subscription --no-pager -l
curl -i http://127.0.0.1:2097/healthz
```

Установить Nginx-конфигурацию:

```bash
sudo install -o root -g root -m 0644 \
  nginx-connect.presentvpn.click.conf \
  /etc/nginx/sites-available/connect.presentvpn.click
sudo ln -sfn \
  /etc/nginx/sites-available/connect.presentvpn.click \
  /etc/nginx/sites-enabled/connect.presentvpn.click
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Проверка снаружи:

```bash
curl -i https://connect.presentvpn.click/healthz
```

## Настройки бота/backend

В `.env` backend:

```dotenv
VPN_SUBSCRIPTION_PUBLIC_BASE_URL=https://connect.presentvpn.click
SUBSCRIPTION_META_REMOTE_TARGET=vpnadmin@139.84.251.197:/opt/vpn-subscription/subscriptions_meta.json
SUBSCRIPTION_META_SSH_KEY=C:\\Users\\User\\.ssh\\presentvpn_za_admin
```

`SUBSCRIPTION_META_SSH_KEY` должен указывать на приватный ключ локально. Сам ключ
никогда не копируется в репозиторий.

## Логи и диагностика

```bash
sudo journalctl -u vpn-subscription -n 100 --no-pager
sudo journalctl -u vpn-subscription -f
sudo nginx -t
sudo tail -n 100 /var/log/nginx/error.log
ss -ltnp | grep -E ':443|:2097'
```

Ожидаемо `2097` слушает только `127.0.0.1`.

## Тесты

```powershell
C:\Users\User\PycharmProjects\pythonProject\.venv\Scripts\python.exe -m ruff check .
C:\Users\User\PycharmProjects\pythonProject\.venv\Scripts\python.exe -m pytest -q
```

Критические сценарии:

- публичный gateway и EU VPN host не смешиваются;
- неизвестный UUID получает `403`;
- валидный UUID из metadata получает subscription;
- истёкшая подписка получает Happ-заглушку;
- приложение слушает локальный HTTP, а TLS завершает Nginx;
- повреждённый metadata-файл не обнуляет последнюю валидную конфигурацию.
