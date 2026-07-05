from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ssl
import base64
import html
import json
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import UUID
import time

HOST = "0.0.0.0"
PORT = 2097

TOKENS_FILE = Path("/opt/vpn-subscription/tokens.txt")
SUBSCRIPTIONS_META_FILE = Path("/opt/vpn-subscription/subscriptions_meta.json")

CERT_FILE = "/root/.acme.sh/lab83607.hostkey.in_ecc/fullchain.cer"
KEY_FILE = "/root/.acme.sh/lab83607.hostkey.in_ecc/lab83607.hostkey.in.key"

DOMAIN = "lab83607.hostkey.in"
PUBLIC_BASE_URL = f"https://{DOMAIN}:{PORT}"

VPN_PORT = 443
WS_PATH = "/ws-test"

HAPP_CRYPTO_API_URL = "https://crypto.happ.su/api-v2.php"


def load_tokens() -> set[str]:
    if not TOKENS_FILE.exists():
        return set()

    tokens: set[str] = set()

    for line in TOKENS_FILE.read_text(encoding="utf-8").splitlines():
        token = line.strip()

        if not token:
            continue

        if token.startswith("#"):
            continue

        tokens.add(token)

    return tokens


def is_uuid_token(token: str) -> bool:
    try:
        UUID(token)
        return True
    except ValueError:
        return False


def is_allowed_token(token: str) -> bool:
    valid_tokens = load_tokens()
    return token in valid_tokens or is_uuid_token(token)

def load_subscriptions_meta() -> dict:
    if not SUBSCRIPTIONS_META_FILE.exists():
        return {}

    try:
        data = json.loads(SUBSCRIPTIONS_META_FILE.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"Failed to load subscriptions meta: {error}")
        return {}

    if not isinstance(data, dict):
        return {}

    return data


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_subscription_meta(client_uuid: str) -> dict[str, int]:
    data = load_subscriptions_meta()
    raw_meta = data.get(client_uuid)

    if not isinstance(raw_meta, dict):
        return {
            "upload": 0,
            "download": 0,
            "total": 0,
            "expire": 0,
        }

    return {
        "upload": _safe_int(raw_meta.get("upload")),
        "download": _safe_int(raw_meta.get("download")),
        "total": _safe_int(raw_meta.get("total")),
        "expire": _safe_int(raw_meta.get("expire")),
    }


def build_subscription_userinfo(client_uuid: str) -> str:
    meta = get_subscription_meta(client_uuid)

    return (
        f"upload={meta['upload']}; "
        f"download={meta['download']}; "
        f"total={meta['total']}; "
        f"expire={meta['expire']}"
    )


def build_vless_link(client_uuid: str) -> str:
    return (
        f"vless://{client_uuid}@{DOMAIN}:{VPN_PORT}"
        f"?alpn=http%2F1.1"
        f"&encryption=none"
        f"&fp=chrome"
        f"&host={DOMAIN}"
        f"&path=%2Fws-test"
        f"&security=tls"
        f"&sni={DOMAIN}"
        f"&type=ws"
        f"#vpn-{client_uuid[:8]}"
    )

def build_expired_vless_link(client_uuid: str) -> str:
    return (
        f"vless://{client_uuid}@127.0.0.1:9"
        f"?encryption=none"
        f"&security=none"
        f"&type=tcp"
        f"#❌ Подписка закончилась — продлите в Telegram"
    )


def is_subscription_expired(client_uuid: str, *, now: int | None = None) -> bool:
    meta = get_subscription_meta(client_uuid)
    expire = meta["expire"]

    if expire <= 0:
        return False

    current_time = int(time.time()) if now is None else int(now)

    return expire <= current_time


def build_subscription_payload(client_uuid: str) -> bytes:
    if is_subscription_expired(client_uuid):
        link = build_expired_vless_link(client_uuid)
    else:
        link = build_vless_link(client_uuid)

    return base64.b64encode((link + "\n").encode("utf-8"))


def build_subscription_url(client_uuid: str) -> str:
    return f"{PUBLIC_BASE_URL}/{client_uuid}"


def get_happ_encrypted_link(subscription_url: str) -> str | None:
    payload = json.dumps({"url": subscription_url}).encode("utf-8")

    request = urllib.request.Request(
        HAPP_CRYPTO_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "vpn-subscription-server/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8").strip()
    except Exception as error:
        print(f"Happ crypto API error: {error}")
        return None

    if not body:
        return None

    candidates = []

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = body

    if isinstance(parsed, str):
        candidates.append(parsed)
    elif isinstance(parsed, dict):
        candidates.extend(str(value) for value in parsed.values())
    elif isinstance(parsed, list):
        candidates.extend(str(value) for value in parsed)

    candidates.append(body)

    for candidate in candidates:
        candidate = html.unescape(candidate).strip().strip('"').replace("\\/", "/")
        marker = "happ://"
        index = candidate.find(marker)

        if index < 0:
            continue

        link = candidate[index:].strip()

        for separator in ['"', "'", "<", " ", "\\n", "\\r", "\\t"]:
            if separator in link:
                link = link.split(separator, 1)[0]

        return link

    print(f"Unexpected Happ crypto API response: {body[:500]}")
    return None


def build_connect_page(
    *,
    client_uuid: str,
    device: str,
    subscription_url: str,
    vless_link: str | None = None,
) -> str:
    safe_device = html.escape(device or "device")
    safe_subscription_url = html.escape(subscription_url, quote=True)
    safe_uuid_short = html.escape(client_uuid[:8])

    deep_link = f"happ://add/{subscription_url}"
    safe_deep_link = html.escape(deep_link, quote=True)

    deep_link_json = json.dumps(deep_link, ensure_ascii=False)
    subscription_json = json.dumps(subscription_url, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Подключение VPN</title>
    <style>
        body {{
            margin: 0;
            padding: 20px;
            min-height: 100vh;
            box-sizing: border-box;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
        }}
        .card {{
            width: 100%;
            max-width: 720px;
            box-sizing: border-box;
            background: #1e293b;
            border: 1px solid rgba(148, 163, 184, .2);
            border-radius: 16px;
            padding: 22px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, .35);
            margin-bottom: 18px;
        }}
        h1 {{
            margin: 0 0 14px;
            font-size: 24px;
        }}
        p, li {{
            font-size: 16px;
            line-height: 1.55;
            color: #cbd5e1;
        }}
        ol {{
            padding-left: 22px;
            margin-bottom: 18px;
        }}
        .muted {{
            color: #94a3b8;
        }}
        .row {{
            display: flex;
            gap: 12px;
            align-items: flex-start;
        }}
        .btn, button {{
            display: inline-block;
            border: 0;
            border-radius: 12px;
            padding: 13px 16px;
            margin-top: 14px;
            font-size: 16px;
            font-weight: 700;
            text-align: center;
            text-decoration: none;
            cursor: pointer;
            background: #334155;
            color: #fff;
        }}
        .primary {{
            background: #2563eb;
        }}
        .success {{
            background: #16a34a;
        }}
        .field-row {{
            display: flex;
            gap: 10px;
            align-items: center;
            margin-top: 12px;
        }}
        input {{
            min-width: 0;
            flex: 1;
            background: #0f172a;
            border: 1px solid #334155;
            color: #cbd5e1;
            padding: 12px;
            border-radius: 12px;
            outline: none;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 14px;
        }}
        code {{
            background: rgba(148, 163, 184, .15);
            padding: 2px 6px;
            border-radius: 6px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Подключение VPN</h1>

        <p>
            Устройство: <b>{safe_device}</b><br>
            Профиль: <b>vpn-{safe_uuid_short}</b>
        </p>

        <div class="row">
            <div>🔗</div>
            <div>
                <div id="status"><b>Пробуем открыть Happ VPN…</b></div>
                <div class="muted">Если ничего не происходит, нажмите кнопку ниже.</div>
            </div>
        </div>

        <a id="openBtn" class="btn success" href="{safe_deep_link}" rel="noopener">
            Открыть вручную
        </a>

        <div class="muted" id="hint" style="margin-top:10px"></div>
    </div>

    <div class="card">
        <h1>Если не получилось открыть автоматически</h1>

        <ol>
            <li>Нажмите кнопку <b>Копировать</b>.</li>
            <li>Откройте Happ VPN.</li>
            <li>Нажмите <b>+</b> в верхнем углу.</li>
            <li>Выберите <b>Импорт/Вставить из буфера</b>.</li>
        </ol>

        <div class="field-row">
            <input type="text" id="subLinkField" value="{safe_subscription_url}" readonly>
            <button id="copyBtn" class="primary">Копировать</button>
        </div>

        <p class="muted">
            Эта ссылка также может быть добавлена как подписка: <code>Subscription / URL</code>.
        </p>
    </div>

    <script>
        const DEEP_LINK = {deep_link_json};
        const SUBSCRIPTION_URL = {subscription_json};

        const hint = document.getElementById("hint");
        const userAgent = navigator.userAgent.toLowerCase();

        if (/android|iphone|ipad|ipod/.test(userAgent)) {{
            hint.textContent = "Если появится запрос на открытие приложения — подтвердите.";
        }} else {{
            hint.innerHTML = "Если появится запрос «Разрешить открыть <code>happ</code>», нажмите «Разрешить».";
        }}

        const AUTO_OPEN_KEY = "vpn_auto_open_" + SUBSCRIPTION_URL;

        if (!sessionStorage.getItem(AUTO_OPEN_KEY)) {{
            sessionStorage.setItem(AUTO_OPEN_KEY, "1");

            setTimeout(function () {{
                location.href = DEEP_LINK;
            }}, 120);
        }}

        function copyToClipboard() {{
            const input = document.getElementById("subLinkField");
            const btn = document.getElementById("copyBtn");

            input.select();
            input.setSelectionRange(0, 99999);

            const done = function () {{
                const oldText = btn.textContent;
                const oldBg = btn.style.background;

                btn.textContent = "Скопировано!";
                btn.style.background = "#16a34a";

                setTimeout(function () {{
                    btn.textContent = oldText;
                    btn.style.background = oldBg;
                }}, 2000);
            }};

            if (navigator.clipboard && window.isSecureContext) {{
                navigator.clipboard.writeText(SUBSCRIPTION_URL).then(done).catch(function () {{
                    document.execCommand("copy");
                    done();
                }});
            }} else {{
                document.execCommand("copy");
                done();
            }}
        }}

        document.getElementById("copyBtn").addEventListener("click", copyToClipboard);
        document.getElementById("subLinkField").addEventListener("click", copyToClipboard);
    </script>
</body>
</html>
"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/sub/"):
            self.handle_subscription(path)
            return

        if path.startswith("/connect/"):
            self.handle_connect(path, parsed.query)
            return

        token = path.strip("/")
        if token and "/" not in token and is_allowed_token(token):
            self.handle_root_subscription(token)
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"not found")

    def handle_root_subscription(self, token: str):
        if not token:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return

        if not is_allowed_token(token):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return

        payload = build_subscription_payload(token)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("profile-update-interval", "1")
        self.send_header("subscription-userinfo", build_subscription_userinfo(token))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def handle_subscription(self, path: str):
        prefix = "/sub/"
        token = path[len(prefix):].strip("/")

        if not token:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return

        if not is_allowed_token(token):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return

        payload = build_subscription_payload(token)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("profile-update-interval", "1")
        self.send_header("subscription-userinfo", build_subscription_userinfo(token))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def handle_connect(self, path: str, query: str):
        prefix = "/connect/"
        token = path[len(prefix):].strip("/")

        if not token:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return

        if not is_allowed_token(token):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return

        query_params = urllib.parse.parse_qs(query)
        device = query_params.get("device", ["unknown"])[0]

        subscription_url = build_subscription_url(token)
        vless_link = build_vless_link(token)

        page = build_connect_page(
            client_uuid=token,
            device=device,
            subscription_url=subscription_url,
            vless_link=vless_link,
        )

        body = page.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def log_message(self, format, *args):
        print(
            "%s - - [%s] %s"
            % (self.client_address[0], self.log_date_time_string(), format % args)
        )


class BetterThreadingHTTPServer(ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


class ThreadedHTTPSServer(BetterThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, ssl_context):
        super().__init__(server_address, RequestHandlerClass)
        self.ssl_context = ssl_context

    def get_request(self):
        sock, addr = self.socket.accept()
        sock.settimeout(10)
        return sock, addr

    def process_request_thread(self, request, client_address):
        ssl_request = None
        try:
            ssl_request = self.ssl_context.wrap_socket(
                request,
                server_side=True,
                do_handshake_on_connect=True,
            )
            ssl_request.settimeout(15)
            self.finish_request(ssl_request, client_address)
            self.shutdown_request(ssl_request)
        except Exception as exc:
            print(f"Client connection error from {client_address}: {exc}")
            try:
                if ssl_request is not None:
                    self.shutdown_request(ssl_request)
                else:
                    self.shutdown_request(request)
            except Exception:
                pass


context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

httpd = ThreadedHTTPSServer((HOST, PORT), Handler, context)

print(f"VPN subscription server started on port {PORT}")
httpd.serve_forever()
