import base64
import html
import json
import logging
import os
import time
from datetime import datetime, timezone
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("vpn-subscription")

HOST = os.getenv("VPN_SUBSCRIPTION_BIND_HOST", "127.0.0.1")
PORT = int(os.getenv("VPN_SUBSCRIPTION_BIND_PORT", "2097"))

SUBSCRIPTIONS_META_FILE = Path(
    os.getenv(
        "VPN_SUBSCRIPTION_META_FILE",
        "/opt/vpn-subscription/subscriptions_meta.json",
    )
)

PUBLIC_BASE_URL = os.getenv(
    "VPN_SUBSCRIPTION_PUBLIC_BASE_URL",
    "https://connect.presentvpn.click",
).rstrip("/")

VPN_HOST = os.getenv("VPN_UPSTREAM_HOST", "eu1.presentvpn.click")
VPN_PORT = int(os.getenv("VPN_UPSTREAM_PORT", "443"))
VPN_WS_PATH = os.getenv("VPN_UPSTREAM_WS_PATH", "/ws-test")
VPN_WS_HOST = os.getenv("VPN_UPSTREAM_WS_HOST", VPN_HOST)
VPN_SNI = os.getenv("VPN_UPSTREAM_SNI", VPN_HOST)

PROFILE_TITLE = os.getenv(
    "VPN_SUBSCRIPTION_PROFILE_TITLE",
    "PRESENT VPN 🎁",
).strip() or "PRESENT VPN"

SERVER_DISPLAY_NAME = os.getenv(
    "VPN_SUBSCRIPTION_SERVER_NAME",
    "🇩🇪 Frankfurt",
).strip() or "🇩🇪 Frankfurt"

# Optional multi-node configuration. When empty or invalid, the service keeps
# the existing single-node behavior from VPN_UPSTREAM_* variables.
VPN_NODES_JSON = os.getenv(
    "VPN_SUBSCRIPTION_NODES_JSON",
    "",
).strip()

TELEGRAM_BOT_URL = os.getenv(
    "VPN_SUBSCRIPTION_TELEGRAM_URL",
    "",
).strip()

PROFILE_WEB_PAGE_URL = os.getenv(
    "VPN_SUBSCRIPTION_PROFILE_WEB_PAGE_URL",
    "",
).strip()

LEGACY_ANNOUNCE_TEMPLATE = os.getenv(
    "VPN_SUBSCRIPTION_ANNOUNCE_TEMPLATE",
    "",
).strip()

ACTIVE_ANNOUNCE_TEMPLATE = os.getenv(
    "VPN_SUBSCRIPTION_ACTIVE_ANNOUNCE_TEMPLATE",
    LEGACY_ANNOUNCE_TEMPLATE
    or "Manage subscription • {telegram} • Days left: {days_left}",
).strip()

EXPIRED_ANNOUNCE_TEMPLATE = os.getenv(
    "VPN_SUBSCRIPTION_EXPIRED_ANNOUNCE_TEMPLATE",
    "Subscription expired on {expires_at} • Renew via {telegram}",
).strip()

HAPP_PROVIDER_ID = os.getenv(
    "VPN_SUBSCRIPTION_HAPP_PROVIDER_ID",
    "",
).strip()

HAPP_INFO_COLOR = os.getenv(
    "VPN_SUBSCRIPTION_HAPP_INFO_COLOR",
    "blue",
).strip().lower()

if HAPP_INFO_COLOR not in {"red", "blue", "green"}:
    HAPP_INFO_COLOR = "blue"

HAPP_INFO_TEMPLATE = os.getenv(
    "VPN_SUBSCRIPTION_HAPP_INFO_TEMPLATE",
    "Manage subscription | {telegram} | Days left: {days_left} | Expires: {expires_at}",
).strip()

HAPP_INFO_BUTTON_TEXT = os.getenv(
    "VPN_SUBSCRIPTION_HAPP_INFO_BUTTON_TEXT",
    "Telegram bot",
).strip()

HAPP_CRYPTO_API_URL = "https://crypto.happ.su/api-v2.php"

_subscriptions_meta_cache: dict = {}
_subscriptions_meta_last_seen_mtime_ns: int | None = None


def is_uuid_token(token: str) -> bool:
    try:
        UUID(token)
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def load_subscriptions_meta() -> dict:
    global _subscriptions_meta_cache
    global _subscriptions_meta_last_seen_mtime_ns

    try:
        mtime_ns = SUBSCRIPTIONS_META_FILE.stat().st_mtime_ns
    except FileNotFoundError:
        _subscriptions_meta_cache = {}
        _subscriptions_meta_last_seen_mtime_ns = None
        return {}
    except OSError as error:
        logger.error("Failed to stat subscriptions metadata: %s", error)
        return dict(_subscriptions_meta_cache)

    if mtime_ns == _subscriptions_meta_last_seen_mtime_ns:
        return dict(_subscriptions_meta_cache)

    _subscriptions_meta_last_seen_mtime_ns = mtime_ns

    try:
        data = json.loads(SUBSCRIPTIONS_META_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.error("Failed to load subscriptions metadata: %s", error)
        return dict(_subscriptions_meta_cache)

    if not isinstance(data, dict):
        logger.error("Subscriptions metadata root must be a JSON object")
        return dict(_subscriptions_meta_cache)

    _subscriptions_meta_cache = data
    return dict(data)


def is_allowed_token(token: str) -> bool:
    if not is_uuid_token(token):
        return False

    return token in load_subscriptions_meta()

def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_status(value) -> str:
    if not isinstance(value, str):
        return ""

    normalized = value.strip().lower()

    if normalized in {"active", "expired", "disabled"}:
        return normalized

    return ""


def get_subscription_meta(client_uuid: str) -> dict[str, int | str]:
    data = load_subscriptions_meta()
    raw_meta = data.get(client_uuid)

    if not isinstance(raw_meta, dict):
        return {
            "status": "",
            "upload": 0,
            "download": 0,
            "total": 0,
            "expire": 0,
        }

    return {
        "status": _safe_status(raw_meta.get("status")),
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


def encode_subscription_header_text(text: str) -> str:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"base64:{encoded}"


def get_subscription_days_left(
    client_uuid: str,
    *,
    now: int | None = None,
) -> int | None:
    expire = get_subscription_meta(client_uuid)["expire"]

    if expire <= 0:
        return None

    current_time = int(time.time()) if now is None else int(now)
    remaining_seconds = expire - current_time

    if remaining_seconds <= 0:
        return 0

    return (remaining_seconds + 86400 - 1) // 86400


def get_subscription_effective_status(
    client_uuid: str,
    *,
    now: int | None = None,
) -> str:
    meta = get_subscription_meta(client_uuid)
    status = str(meta["status"])
    expire = int(meta["expire"])
    current_time = int(time.time()) if now is None else int(now)

    if status in {"expired", "disabled"}:
        return "expired"

    if expire > 0 and expire <= current_time:
        return "expired"

    return "active"


def get_subscription_expiry_date(client_uuid: str) -> str:
    expire = int(get_subscription_meta(client_uuid)["expire"])

    if expire <= 0:
        return "unknown"

    return datetime.fromtimestamp(
        expire,
        tz=timezone.utc,
    ).strftime("%d.%m.%Y")


def get_website_label() -> str:
    if not PROFILE_WEB_PAGE_URL:
        return "website"

    parsed = urllib.parse.urlparse(PROFILE_WEB_PAGE_URL)
    host = parsed.netloc.strip()

    return host or "website"


def get_telegram_label() -> str:
    if not TELEGRAM_BOT_URL:
        return "Telegram bot"

    parsed = urllib.parse.urlparse(TELEGRAM_BOT_URL)
    username = parsed.path.strip("/").split("/")[-1]

    if username:
        return f"@{username.lstrip('@')}"

    return "Telegram bot"


def build_announce_text(
    client_uuid: str,
    *,
    now: int | None = None,
) -> str:
    days_left = get_subscription_days_left(client_uuid, now=now)
    days_value = "∞" if days_left is None else str(days_left)
    effective_status = get_subscription_effective_status(
        client_uuid,
        now=now,
    )
    template = (
        EXPIRED_ANNOUNCE_TEMPLATE
        if effective_status == "expired"
        else ACTIVE_ANNOUNCE_TEMPLATE
    )

    values = {
        "telegram": get_telegram_label(),
        "website": get_website_label(),
        "days_left": days_value,
        "expires_at": get_subscription_expiry_date(client_uuid),
    }

    try:
        text = template.format(**values)
    except (KeyError, ValueError):
        logger.error(
            "Invalid subscription announce template; using fallback"
        )

        if effective_status == "expired":
            text = (
                f"Subscription expired on {values['expires_at']} "
                f"• Renew via {values['telegram']}"
            )
        else:
            text = (
                f"Manage subscription • {values['telegram']} "
                f"• Days left: {days_value}"
            )

    return text[:200]


def build_happ_info_text(
    client_uuid: str,
    *,
    now: int | None = None,
) -> str:
    days_left = get_subscription_days_left(client_uuid, now=now)
    days_value = "unknown" if days_left is None else str(days_left)

    values = {
        "telegram": get_telegram_label(),
        "website": get_website_label(),
        "days_left": days_value,
        "expires_at": get_subscription_expiry_date(client_uuid),
    }

    try:
        text = HAPP_INFO_TEMPLATE.format(**values)
    except (KeyError, ValueError):
        logger.error(
            "Invalid VPN_SUBSCRIPTION_HAPP_INFO_TEMPLATE; using fallback"
        )
        text = (
            f"Manage subscription | {values['telegram']} "
            f"| Days left: {days_value} "
            f"| Expires: {values['expires_at']}"
        )

    # Happ documents a 200 character maximum for sub-info-text.
    return text[:200]

def build_subscription_metadata_headers(client_uuid: str) -> dict[str, str]:
    headers = {
        "profile-update-interval": "1",
        "subscription-userinfo": build_subscription_userinfo(client_uuid),
        "profile-title": encode_subscription_header_text(PROFILE_TITLE[:25]),
        "announce": encode_subscription_header_text(
            build_announce_text(client_uuid)
        ),
    }

    if TELEGRAM_BOT_URL:
        headers["support-url"] = TELEGRAM_BOT_URL
        headers["announce-url"] = TELEGRAM_BOT_URL

    if PROFILE_WEB_PAGE_URL:
        headers["profile-web-page-url"] = PROFILE_WEB_PAGE_URL

    if HAPP_PROVIDER_ID:
        headers["providerid"] = HAPP_PROVIDER_ID
        headers["sub-info-color"] = HAPP_INFO_COLOR
        headers["sub-info-text"] = build_happ_info_text(client_uuid)

        if HAPP_INFO_BUTTON_TEXT and TELEGRAM_BOT_URL:
            headers["sub-info-button-text"] = HAPP_INFO_BUTTON_TEXT[:25]
            headers["sub-info-button-link"] = TELEGRAM_BOT_URL

        headers["sub-expire"] = "1"

        if TELEGRAM_BOT_URL:
            headers["sub-expire-button-link"] = TELEGRAM_BOT_URL

    return headers


def _legacy_vpn_node() -> dict[str, str | int]:
    return {
        "name": SERVER_DISPLAY_NAME,
        "host": VPN_HOST,
        "port": VPN_PORT,
        "ws_path": VPN_WS_PATH,
        "ws_host": VPN_WS_HOST,
        "sni": VPN_SNI,
    }


def load_vpn_nodes() -> list[dict[str, str | int]]:
    if not VPN_NODES_JSON:
        return [_legacy_vpn_node()]

    try:
        raw_nodes = json.loads(VPN_NODES_JSON)
    except json.JSONDecodeError as error:
        logger.error(
            "Invalid VPN_SUBSCRIPTION_NODES_JSON; using legacy node: %s",
            error,
        )
        return [_legacy_vpn_node()]

    if not isinstance(raw_nodes, list):
        logger.error(
            "VPN_SUBSCRIPTION_NODES_JSON must contain a JSON array; "
            "using legacy node"
        )
        return [_legacy_vpn_node()]

    nodes: list[dict[str, str | int]] = []

    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            logger.error("Ignoring VPN node %s: expected JSON object", index)
            continue

        if raw_node.get("enabled", True) is False:
            continue

        name = str(raw_node.get("name", "")).strip()
        host = str(raw_node.get("host", "")).strip()
        ws_path = str(raw_node.get("ws_path", "/ws-test")).strip()
        ws_host = str(raw_node.get("ws_host", host)).strip()
        sni = str(raw_node.get("sni", host)).strip()

        try:
            port = int(raw_node.get("port", 443))
        except (TypeError, ValueError):
            port = 0

        if not name or not host or not ws_host or not sni:
            logger.error(
                "Ignoring VPN node %s: name/host/ws_host/sni are required",
                index,
            )
            continue

        if not ws_path.startswith("/"):
            logger.error(
                "Ignoring VPN node %s: ws_path must start with /",
                index,
            )
            continue

        if port < 1 or port > 65535:
            logger.error("Ignoring VPN node %s: invalid port", index)
            continue

        nodes.append(
            {
                "name": name,
                "host": host,
                "port": port,
                "ws_path": ws_path,
                "ws_host": ws_host,
                "sni": sni,
            }
        )

    if not nodes:
        logger.error(
            "VPN_SUBSCRIPTION_NODES_JSON has no enabled valid nodes; "
            "using legacy node"
        )
        return [_legacy_vpn_node()]

    return nodes


def build_vless_link(
    client_uuid: str,
    node: dict[str, str | int] | None = None,
) -> str:
    selected = _legacy_vpn_node() if node is None else node
    host = str(selected["host"])
    port = int(selected["port"])
    ws_path = str(selected["ws_path"])
    ws_host = str(selected["ws_host"])
    sni = str(selected["sni"])
    server_display_name = str(selected["name"])

    query = urllib.parse.urlencode(
        [
            ("alpn", "http/1.1"),
            ("encryption", "none"),
            ("fp", "chrome"),
            ("host", ws_host),
            ("path", ws_path),
            ("security", "tls"),
            ("sni", sni),
            ("type", "ws"),
        ],
        quote_via=urllib.parse.quote,
    )

    display_name = urllib.parse.quote(server_display_name, safe="")

    return (
        f"vless://{client_uuid}@{host}:{port}"
        f"?{query}"
        f"#{display_name}"
    )


def build_vless_links(client_uuid: str) -> list[str]:
    return [
        build_vless_link(client_uuid, node)
        for node in load_vpn_nodes()
    ]

def build_expired_vless_link(client_uuid: str) -> str:
    return (
        f"vless://{client_uuid}@127.0.0.1:9"
        f"?encryption=none"
        f"&security=none"
        f"&type=tcp"
        f"#❌ Subscription expired — renew in Telegram"
    )


def is_subscription_expired(client_uuid: str, *, now: int | None = None) -> bool:
    return get_subscription_effective_status(
        client_uuid,
        now=now,
    ) == "expired"


def build_subscription_payload(client_uuid: str) -> bytes:
    if is_subscription_expired(client_uuid):
        links = [build_expired_vless_link(client_uuid)]
    else:
        links = build_vless_links(client_uuid)

    return base64.b64encode(("\n".join(links) + "\n").encode("utf-8"))


def build_subscription_url(client_uuid: str) -> str:
    return f"{PUBLIC_BASE_URL}/{client_uuid}"


def build_v2raytun_deep_link(subscription_url: str) -> str:
    return f"v2raytun://import/{subscription_url}"


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
    except Exception:
        logger.exception("Happ crypto API request failed.")
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
    client: str = "happ",
    vless_link: str | None = None,
) -> str:
    safe_device = html.escape(device or "device")
    safe_subscription_url = html.escape(subscription_url, quote=True)
    safe_uuid_short = html.escape(client_uuid[:8])

    normalized_client = client.strip().lower()

    if normalized_client == "happ":
        app_name = "Happ VPN"
        client_scheme = "happ"
        deep_link = f"happ://add/{subscription_url}"
    elif normalized_client == "v2raytun":
        app_name = "v2RayTun"
        client_scheme = "v2raytun"
        deep_link = build_v2raytun_deep_link(subscription_url)
    else:
        raise ValueError(f"Unsupported VPN client: {client}")

    safe_app_name = html.escape(app_name)
    safe_deep_link = html.escape(deep_link, quote=True)

    deep_link_json = json.dumps(deep_link, ensure_ascii=False)
    client_scheme_json = json.dumps(client_scheme, ensure_ascii=False)
    subscription_json = json.dumps(subscription_url, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>VPN Connection</title>
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
        <h1>VPN Connection</h1>

        <p>
            Device: <b>{safe_device}</b><br>
            Profile: <b>vpn-{safe_uuid_short}</b>
        </p>

        <div class="row">
            <div>🔗</div>
            <div>
                <div id="status"><b>Trying to open {safe_app_name}…</b></div>
                <div class="muted">If nothing happens, click the button below.</div>
            </div>
        </div>

        <a id="openBtn" class="btn success" href="{safe_deep_link}" rel="noopener">
            Open Manually
        </a>

        <div class="muted" id="hint" style="margin-top:10px"></div>
    </div>

    <div class="card">
        <h1>If the app did not open automatically</h1>

        <ol>
            <li>Click <b>Open Manually</b> above.</li>
            <li>If that does not work, click <b>Copy</b>.</li>
            <li>Open {safe_app_name}.</li>
            <li>Import the copied link as <b>Subscription / URL</b>.</li>
        </ol>

        <div class="field-row">
            <input type="text" id="subLinkField" value="{safe_subscription_url}" readonly>
            <button id="copyBtn" class="primary">Copy</button>
        </div>

        <p class="muted">
            This link can also be added as a subscription: <code>Subscription / URL</code>.
        </p>
    </div>

    <script>
        const DEEP_LINK = {deep_link_json};
        const CLIENT_SCHEME = {client_scheme_json};
        const SUBSCRIPTION_URL = {subscription_json};

        const hint = document.getElementById("hint");
        const userAgent = navigator.userAgent.toLowerCase();

        if (/android|iphone|ipad|ipod/.test(userAgent)) {{
            hint.textContent = "If prompted to open the app, confirm it.";
        }} else {{
            hint.innerHTML =
                "If you see “Allow this page to open <code>" +
                CLIENT_SCHEME +
                "</code>”, click “Allow”.";
                    }}

        const AUTO_OPEN_KEY =
            "vpn_auto_open_" + CLIENT_SCHEME + "_" + SUBSCRIPTION_URL;

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

                btn.textContent = "Copied!";
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

        if path == "/healthz":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return

        token = path.strip("/")
        if token and "/" not in token and is_uuid_token(token):
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
        for key, value in build_subscription_metadata_headers(token).items():
            self.send_header(key, value)
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
        for key, value in build_subscription_metadata_headers(token).items():
            self.send_header(key, value)
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
        client = query_params.get("client", ["happ"])[0].strip().lower()

        if client not in {"happ", "v2raytun"}:
            body = b"unsupported client"

            self.send_response(400)
            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return

        subscription_url = build_subscription_url(token)
        vless_link = build_vless_link(token)

        page = build_connect_page(
            client_uuid=token,
            device=device,
            subscription_url=subscription_url,
            client=client,
            vless_link=vless_link,
        )

        body = page.encode("utf-8")

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


    def log_message(self, format, *args):
        logger.info(
            "%s - - [%s] %s",
            self.client_address[0],
            self.log_date_time_string(),
            format % args,
        )


class BetterThreadingHTTPServer(ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(15)
        return request, client_address


def main() -> None:
    httpd = BetterThreadingHTTPServer((HOST, PORT), Handler)
    logger.info(
        "VPN subscription server started on http://%s:%s; public=%s; vpn_upstream=%s:%s",
        HOST,
        PORT,
        PUBLIC_BASE_URL,
        VPN_HOST,
        VPN_PORT,
    )

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("VPN subscription server stopping")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
