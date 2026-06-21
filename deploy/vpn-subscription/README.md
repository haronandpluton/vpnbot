# VPN Subscription Server

Отдельный HTTPS-сервер для Happ-compatible выдачи VPN-подписки.

Сервер отвечает за:

* страницу подключения `/connect/<uuid>`
* основной subscription endpoint `/<uuid>`
* технический fallback endpoint `/sub/<uuid>`
* автообновление подписки в Happ
* отображение срока подписки в Happ
* заглушку при истёкшей подписке

---

## 1. Основная схема

Рабочий пользовательский flow:

```text
Telegram bot
→ https://DOMAIN:PORT/connect/<uuid>?device=android|ios
→ setup-страница
→ happ://add/https://DOMAIN:PORT/<uuid>
→ Happ VPN
→ автоматический импорт подписки
→ автообновление подписки раз в час
```

Основной Happ deep link:

```text
happ://add/https://DOMAIN:PORT/<uuid>
```

Не использовать как основной deep link:

```text
happ://add/https://DOMAIN:PORT/sub/<uuid>
```

`/sub/<uuid>` оставлен только как технический fallback.

---

## 2. Endpoints

### `GET /<uuid>`

Основной Happ-compatible subscription endpoint.

Возвращает base64-encoded subscription body с VLESS-ссылкой.

Пример:

```text
https://lab83607.hostkey.in:2097/62486a8e-b420-44af-8bd8-fb8cc061a93b
```

---

### `GET /sub/<uuid>`

Технический fallback endpoint.

Пример:

```text
https://lab83607.hostkey.in:2097/sub/62486a8e-b420-44af-8bd8-fb8cc061a93b
```

Для Happ как основной endpoint не использовать.

---

### `GET /connect/<uuid>?device=android|ios`

Пользовательская страница подключения.

Пример:

```text
https://lab83607.hostkey.in:2097/connect/62486a8e-b420-44af-8bd8-fb8cc061a93b?device=android
```

Страница:

* автоматически пытается открыть Happ
* использует `happ://add/https://DOMAIN:PORT/<uuid>`
* содержит кнопку `Открыть вручную`
* содержит fallback-кнопку `Копировать`
* копирует именно `https://DOMAIN:PORT/<uuid>`, а не `/sub/<uuid>`

---

## 3. Обязательные HTTP-заголовки

Для `/<uuid>` и `/sub/<uuid>` должны быть:

```http
Content-Type: text/plain; charset=utf-8
Cache-Control: no-store
profile-update-interval: 1
subscription-userinfo: upload=0; download=0; total=0; expire=<unix_timestamp>
Content-Length: ...
Connection: close
```

---

## 4. Автообновление Happ

Заголовок:

```http
profile-update-interval: 1
```

означает, что Happ будет обновлять subscription URL раз в 1 час.

Это нужно для:

* обновления срока подписки
* будущей подмены серверов
* будущей выдачи нескольких серверов
* будущей заглушки при окончании подписки

---

## 5. Срок подписки в Happ

Заголовок:

```http
subscription-userinfo: upload=0; download=0; total=0; expire=<unix_timestamp>
```

Пример:

```http
subscription-userinfo: upload=0; download=0; total=0; expire=1782000000
```

Поля:

```text
upload   — использованный upload в байтах
download — использованный download в байтах
total    — общий лимит трафика в байтах
expire   — дата окончания подписки в Unix timestamp
```

На текущем временном сервере:

```text
upload=0
download=0
total=0
```

`total=0` используется как отсутствие отображаемого лимита трафика. В Happ это отображается как `∞`.

---

## 6. Временный источник срока подписки

Пока срок подписки берётся из локального JSON-файла:

```text
/opt/vpn-subscription/subscriptions_meta.json
```

Пример:

```json
{
  "62486a8e-b420-44af-8bd8-fb8cc061a93b": {
    "expire": 1782000000,
    "upload": 0,
    "download": 0,
    "total": 0
  }
}
```

Это временная схема.

В production источник истины должен быть:

```text
БД бота / backend API
```

а не локальный JSON-файл.

---

## 7. Поведение при активной подписке

Если:

```text
expire > now
```

сервер отдаёт рабочий VLESS-профиль:

```text
vless://<uuid>@DOMAIN:443?...#vpn-<uuid-prefix>
```

Пример:

```text
vless://62486a8e-b420-44af-8bd8-fb8cc061a93b@lab83607.hostkey.in:443?alpn=http%2F1.1&encryption=none&fp=chrome&host=lab83607.hostkey.in&path=%2Fws-test&security=tls&sni=lab83607.hostkey.in&type=ws#vpn-62486a8e
```

---

## 8. Поведение при истёкшей подписке

Если:

```text
expire <= now
```

сервер отдаёт один нерабочий VLESS-профиль с названием:

```text
❌ Подписка закончилась — продлите в Telegram
```

Технически это выглядит как VLESS-ссылка на нерабочий локальный адрес:

```text
vless://<uuid>@127.0.0.1:9?encryption=none&security=none&type=tcp#...
```

Это нужно, чтобы в Happ пользователь видел понятную заглушку, а не просто пустую подписку или ошибку импорта.

---

## 9. Runtime files на сервере

Рабочая директория:

```text
/opt/vpn-subscription
```

Файлы:

```text
/opt/vpn-subscription/sub_server.py
/opt/vpn-subscription/tokens.txt
/opt/vpn-subscription/subscriptions_meta.json
```

---

## 10. Systemd service

Файл:

```text
/etc/systemd/system/vpn-subscription.service
```

Содержимое:

```ini
[Unit]
Description=VPN Subscription Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/vpn-subscription
ExecStart=/usr/bin/python3 /opt/vpn-subscription/sub_server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

---

## 11. Проверка после изменений

Проверка синтаксиса:

```bash
python3 -m py_compile /opt/vpn-subscription/sub_server.py
```

Рестарт:

```bash
systemctl restart vpn-subscription
sleep 2
systemctl status vpn-subscription --no-pager -l
```

Проверка порта:

```bash
ss -ltnp | grep ':2097'
```

---

## 12. Проверка root subscription endpoint

```bash
UUID="62486a8e-b420-44af-8bd8-fb8cc061a93b"

curl -k -sS -D /tmp/sub_root_headers.txt \
  -o /tmp/sub_root_body.txt \
  "https://127.0.0.1:2097/$UUID"

cat /tmp/sub_root_headers.txt | grep -Ei "HTTP/|content-type|content-length|connection|profile-update|subscription-userinfo"

base64 -d /tmp/sub_root_body.txt
```

Ожидаемо для активной подписки:

```text
profile-update-interval: 1
subscription-userinfo: upload=0; download=0; total=0; expire=<future_timestamp>

vless://<uuid>@lab83607.hostkey.in:443...
```

---

## 13. Проверка fallback `/sub/<uuid>`

```bash
UUID="62486a8e-b420-44af-8bd8-fb8cc061a93b"

curl -k -sS -D /tmp/sub_legacy_headers.txt \
  -o /tmp/sub_legacy_body.txt \
  "https://127.0.0.1:2097/sub/$UUID"

cat /tmp/sub_legacy_headers.txt | grep -Ei "HTTP/|content-type|content-length|connection|profile-update|subscription-userinfo"

base64 -d /tmp/sub_legacy_body.txt
```

Ожидаемо то же поведение, что у `/<uuid>`.

---

## 14. Проверка `/connect`

```bash
UUID="62486a8e-b420-44af-8bd8-fb8cc061a93b"

curl -k -sS \
  "https://127.0.0.1:2097/connect/$UUID?device=android" \
  -o /tmp/connect_test.html

grep -E "happ://add|sessionStorage|setTimeout|Открыть вручную|Копировать" -n /tmp/connect_test.html
```

Ожидаемо:

```text
happ://add/https://lab83607.hostkey.in:2097/<uuid>
sessionStorage
setTimeout
Открыть вручную
Копировать
```

---

## 15. Проверка истёкшей подписки

Временно поставить `expire` в прошлое:

```bash
python3 - <<'PY'
from pathlib import Path
import json
import time

uuid = "62486a8e-b420-44af-8bd8-fb8cc061a93b"
path = Path("/opt/vpn-subscription/subscriptions_meta.json")

data = json.loads(path.read_text(encoding="utf-8"))
data.setdefault(uuid, {})
data[uuid]["expire"] = int(time.time()) - 60
data[uuid]["upload"] = 0
data[uuid]["download"] = 0
data[uuid]["total"] = 0

path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(json.dumps(data[uuid], ensure_ascii=False, indent=2))
PY
```

Проверить:

```bash
UUID="62486a8e-b420-44af-8bd8-fb8cc061a93b"

curl -k -sS -D /tmp/expired_headers.txt \
  -o /tmp/expired_body.txt \
  "https://127.0.0.1:2097/$UUID"

cat /tmp/expired_headers.txt | grep -Ei "HTTP/|profile-update|subscription-userinfo"

base64 -d /tmp/expired_body.txt
```

Ожидаемо:

```text
subscription-userinfo: upload=0; download=0; total=0; expire=<past_timestamp>

vless://<uuid>@127.0.0.1:9?encryption=none&security=none&type=tcp#...
```

В Happ должен появиться профиль:

```text
❌ Подписка закончилась — продлите в Telegram
```

---

## 16. Вернуть подписку активной

После теста вернуть дату в будущее:

```bash
python3 - <<'PY'
from pathlib import Path
import json
import time

uuid = "62486a8e-b420-44af-8bd8-fb8cc061a93b"
path = Path("/opt/vpn-subscription/subscriptions_meta.json")

data = json.loads(path.read_text(encoding="utf-8"))
data.setdefault(uuid, {})
data[uuid]["expire"] = int(time.time()) + 30 * 24 * 60 * 60
data[uuid]["upload"] = 0
data[uuid]["download"] = 0
data[uuid]["total"] = 0

path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(json.dumps(data[uuid], ensure_ascii=False, indent=2))
PY
```

Проверить:

```bash
UUID="62486a8e-b420-44af-8bd8-fb8cc061a93b"

curl -k -sS -o /tmp/active_body.txt \
  "https://127.0.0.1:2097/$UUID"

base64 -d /tmp/active_body.txt
```

Ожидаемо:

```text
vless://<uuid>@lab83607.hostkey.in:443...
```

---

## 17. Важные технические требования

Subscription server должен использовать:

```text
ThreadingHTTPServer
request_queue_size = 256
daemon_threads = True
TLS-handshake в worker-потоке
```

Не использовать:

```python
httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
```

Потому что это может блокировать главный accept-поток и вызывать вечную загрузку.

---

## 18. Production note

Текущая схема с `subscriptions_meta.json` — временная.

В production нужно заменить JSON на:

```text
subscription-server → backend API / database
```

Источник истины:

```text
users
orders
payments
subscriptions
vpn_servers
```

Тогда subscription-server сможет отдавать:

* актуальный `expires_at`
* статус подписки
* несколько серверов
* заглушку при истёкшей подписке
* реальные upload/download/total

---

## 19. Что не входит в текущую временную версию

Пока не реализовано:

* реальный upload/download
* реальный лимит трафика
* блокировка по превышению трафика
* несколько VPN-серверов
* автоматическая подмена серверов
* RU front-gateway на 443
* чтение подписок из БД

Эти пункты относятся к следующему production-этапу.

---

## 20. Текущий тестовый сервер

```text
DOMAIN=lab83607.hostkey.in
IP=151.243.212.64
VPN_PORT=443
WS_PATH=/ws-test
SUB_PORT=2097
```

Рабочие URL:

```text
Happ subscription:
https://lab83607.hostkey.in:2097/<uuid>

Happ deep link:
happ://add/https://lab83607.hostkey.in:2097/<uuid>

Setup page:
https://lab83607.hostkey.in:2097/connect/<uuid>?device=android

Technical fallback:
https://lab83607.hostkey.in:2097/sub/<uuid>
```
