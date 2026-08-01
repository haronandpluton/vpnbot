from __future__ import annotations

import base64
import io
import json
import types
import urllib.parse
from pathlib import Path

SUB_SERVER_PATH = Path("deploy/vpn-subscription/sub_server.py")
VALID_UUID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_UUID = "99999999-9999-4999-8999-999999999999"


def load_sub_server_without_startup():
    source = SUB_SERVER_PATH.read_text(encoding="utf-8")
    prefix = source.split('\nif __name__ == "__main__":', 1)[0]
    module = types.ModuleType("sub_server_under_test")
    exec(compile(prefix, str(SUB_SERVER_PATH), "exec"), module.__dict__)
    return module


def write_allowed_metadata(
    module,
    tmp_path,
    *,
    expire: int = 9999999999,
    status: str = "active",
) -> None:
    meta_file = tmp_path / "subscriptions_meta.json"
    meta_file.write_text(
        json.dumps(
            {
                VALID_UUID: {
                    "status": status,
                    "upload": 0,
                    "download": 0,
                    "total": 0,
                    "expire": expire,
                }
            }
        ),
        encoding="utf-8",
    )
    module.SUBSCRIPTIONS_META_FILE = meta_file
    module._subscriptions_meta_cache = {}
    module._subscriptions_meta_last_seen_mtime_ns = None


def decode_base64_header(value: str) -> str:
    assert value.startswith("base64:")
    return base64.b64decode(value[len("base64:"):]).decode("utf-8")


class HandlerHarness:
    def __init__(self, module, *, path: str) -> None:
        self.module = module
        self.handler = object.__new__(module.Handler)
        self.handler.path = path
        self.handler.wfile = io.BytesIO()
        self.handler.client_address = ("127.0.0.1", 12345)
        self.handler.close_connection = False
        self.responses: list[int] = []
        self.headers: list[tuple[str, str]] = []
        self.ended = False

        self.handler.send_response = self.send_response
        self.handler.send_header = self.send_header
        self.handler.end_headers = self.end_headers

    def send_response(self, code: int) -> None:
        self.responses.append(code)

    def send_header(self, key: str, value: str) -> None:
        self.headers.append((key, value))

    def end_headers(self) -> None:
        self.ended = True

    def do_get(self):
        self.handler.do_GET()
        return self

    @property
    def body(self) -> bytes:
        return self.handler.wfile.getvalue()

    @property
    def header_map(self) -> dict[str, str]:
        return dict(self.headers)


def test_subscription_server_source_uses_local_threaded_http_behind_nginx():
    source = SUB_SERVER_PATH.read_text(encoding="utf-8")

    assert 'HOST = os.getenv("VPN_SUBSCRIPTION_BIND_HOST", "127.0.0.1")' in source
    assert "class BetterThreadingHTTPServer(ThreadingHTTPServer):" in source
    assert "request_queue_size = 256" in source
    assert "daemon_threads = True" in source
    assert "httpd = BetterThreadingHTTPServer((HOST, PORT), Handler)" in source
    assert "ssl.SSLContext" not in source
    assert "CERT_FILE" not in source
    assert "KEY_FILE" not in source


def test_allowed_token_requires_uuid_present_in_subscription_metadata(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)

    assert module.is_allowed_token(VALID_UUID) is True
    assert module.is_allowed_token(UNKNOWN_UUID) is False
    assert module.is_allowed_token("not-a-uuid") is False


def test_vless_link_separates_public_gateway_from_eu_vpn_upstream():
    module = load_sub_server_without_startup()
    module.PUBLIC_BASE_URL = "https://connect.example.com"
    module.VPN_HOST = "eu-vpn.example.com"
    module.VPN_PORT = 443
    module.VPN_WS_PATH = "/ws-test"
    module.VPN_WS_HOST = "eu-vpn.example.com"
    module.VPN_SNI = "eu-vpn.example.com"
    module.SERVER_DISPLAY_NAME = "🇫🇷 France #01"

    link = module.build_vless_link(VALID_UUID)

    assert link.startswith(f"vless://{VALID_UUID}@eu-vpn.example.com:443?")
    assert "connect.example.com" not in link
    assert "security=tls" in link
    assert "type=ws" in link
    assert "path=%2Fws-test" in link
    assert "host=eu-vpn.example.com" in link
    assert "sni=eu-vpn.example.com" in link
    assert "fp=chrome" in link
    assert "alpn=http%2F1.1" in link
    assert urllib.parse.unquote(link.split("#", 1)[1]) == "🇫🇷 France #01"


def test_subscription_url_uses_public_root_uuid_endpoint_not_sub_path():
    module = load_sub_server_without_startup()
    module.PUBLIC_BASE_URL = "https://connect.example.com"

    assert module.build_subscription_url(VALID_UUID) == (
        f"https://connect.example.com/{VALID_UUID}"
    )
    assert "/sub/" not in module.build_subscription_url(VALID_UUID)


def test_connect_page_defaults_to_happ_and_keeps_copy_fallback():
    module = load_sub_server_without_startup()
    subscription_url = f"https://connect.example.com/{VALID_UUID}"

    page = module.build_connect_page(
        client_uuid=VALID_UUID,
        device="android",
        subscription_url=subscription_url,
    )

    assert f"happ://add/{subscription_url}" in page
    assert f'value="{subscription_url}"' in page

    assert 'const CLIENT_SCHEME = "happ"' in page
    assert (
        '"vpn_auto_open_" + CLIENT_SCHEME + "_" + SUBSCRIPTION_URL'
        in page
    )

    assert "sessionStorage" in page
    assert "setTimeout(function ()" in page
    assert "location.href = DEEP_LINK" in page
    assert "Open Manually" in page
    assert "Copy" in page

    assert "/sub/" not in page

def test_root_subscription_endpoint_returns_base64_vless_and_required_headers(
    tmp_path,
):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)
    module.VPN_HOST = "eu-vpn.example.com"
    module.VPN_WS_HOST = "eu-vpn.example.com"
    module.VPN_SNI = "eu-vpn.example.com"

    harness = HandlerHarness(module, path=f"/{VALID_UUID}").do_get()

    assert harness.responses == [200]
    assert harness.header_map["Content-Type"] == "text/plain; charset=utf-8"
    assert harness.header_map["profile-update-interval"] == "1"
    assert harness.header_map["subscription-userinfo"].endswith(
        "expire=9999999999"
    )
    assert decode_base64_header(harness.header_map["profile-title"]) == (
        "PRESENT VPN 🎁"
    )
    assert "Days left:" in decode_base64_header(harness.header_map["announce"])
    assert harness.header_map["Cache-Control"] == "no-store"
    assert harness.header_map["Connection"] == "close"
    assert int(harness.header_map["Content-Length"]) == len(harness.body)
    assert harness.handler.close_connection is True

    decoded = base64.b64decode(harness.body).decode("utf-8")
    assert decoded.startswith(f"vless://{VALID_UUID}@eu-vpn.example.com:443")
    assert decoded.endswith("\n")


def test_sub_fallback_endpoint_returns_same_subscription_payload_and_headers(
    tmp_path,
):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)
    module.VPN_HOST = "eu-vpn.example.com"
    module.VPN_WS_HOST = "eu-vpn.example.com"
    module.VPN_SNI = "eu-vpn.example.com"

    harness = HandlerHarness(module, path=f"/sub/{VALID_UUID}").do_get()

    assert harness.responses == [200]
    assert harness.header_map["Content-Type"] == "text/plain; charset=utf-8"
    assert harness.header_map["profile-update-interval"] == "1"
    assert harness.header_map["Cache-Control"] == "no-store"
    assert harness.header_map["Connection"] == "close"
    assert int(harness.header_map["Content-Length"]) == len(harness.body)

    decoded = base64.b64decode(harness.body).decode("utf-8")
    assert decoded.startswith(f"vless://{VALID_UUID}@eu-vpn.example.com:443")


def test_connect_endpoint_defaults_to_happ_for_backward_compatibility(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)
    module.PUBLIC_BASE_URL = "https://connect.example.com"

    harness = HandlerHarness(
        module,
        path=f"/connect/{VALID_UUID}?device=ios",
    ).do_get()

    assert harness.responses == [200]
    assert harness.header_map["Content-Type"] == "text/html; charset=utf-8"
    assert harness.header_map["Cache-Control"] == "no-store"
    assert harness.header_map["Connection"] == "close"
    assert int(harness.header_map["Content-Length"]) == len(harness.body)
    assert harness.handler.close_connection is True

    page = harness.body.decode("utf-8")

    assert "Device: <b>ios</b>" in page
    assert (
        f"happ://add/https://connect.example.com/{VALID_UUID}"
        in page
    )
    assert 'const CLIENT_SCHEME = "happ"' in page
    assert (
        f'value="https://connect.example.com/{VALID_UUID}"'
        in page
    )
    assert "sessionStorage" in page


def test_subscription_metadata_headers_include_branding_links_and_dynamic_days(
    tmp_path,
):
    module = load_sub_server_without_startup()
    expire = 2_000_000_000
    write_allowed_metadata(module, tmp_path, expire=expire)

    module.PROFILE_TITLE = "🎁 PRESENT VPN"
    module.TELEGRAM_BOT_URL = "https://t.me/PresentVPNBot"
    module.PROFILE_WEB_PAGE_URL = "https://presentvpn.example.com"
    module.ACTIVE_ANNOUNCE_TEMPLATE = (
        "Manage: {website} • {telegram} • Days left: {days_left}"
    )
    module.EXPIRED_ANNOUNCE_TEMPLATE = (
        "Subscription expired on {expires_at} • Renew via {telegram}"
    )

    now = expire - 26 * 86400

    assert module.get_subscription_days_left(VALID_UUID, now=now) == 26
    assert module.build_announce_text(VALID_UUID, now=now) == (
        "Manage: presentvpn.example.com • @PresentVPNBot • Days left: 26"
    )

    headers = module.build_subscription_metadata_headers(VALID_UUID)

    assert decode_base64_header(headers["profile-title"]) == "🎁 PRESENT VPN"
    assert headers["support-url"] == "https://t.me/PresentVPNBot"
    assert headers["announce-url"] == "https://t.me/PresentVPNBot"
    assert headers["profile-web-page-url"] == "https://presentvpn.example.com"

    # Unicode branding must stay ASCII-safe at HTTP header level.
    headers["profile-title"].encode("latin-1")
    headers["announce"].encode("latin-1")


def test_subscription_payload_supports_multiple_configured_nodes(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)
    module.VPN_NODES_JSON = json.dumps(
        [
            {
                "name": "🇩🇪 Frankfurt",
                "host": "eu1.presentvpn.click",
                "port": 443,
                "ws_path": "/ws-test",
                "ws_host": "eu1.presentvpn.click",
                "sni": "eu1.presentvpn.click",
            },
            {
                "name": "🇳🇱 Netherlands",
                "host": "nl1.presentvpn.click",
                "port": 443,
                "ws_path": "/ws-test",
                "ws_host": "nl1.presentvpn.click",
                "sni": "nl1.presentvpn.click",
            },
        ],
        ensure_ascii=False,
    )

    payload = module.build_subscription_payload(VALID_UUID)
    decoded = base64.b64decode(payload).decode("utf-8")
    lines = [line for line in decoded.splitlines() if line]

    assert len(lines) == 2
    assert lines[0].startswith(
        f"vless://{VALID_UUID}@eu1.presentvpn.click:443"
    )
    assert lines[1].startswith(
        f"vless://{VALID_UUID}@nl1.presentvpn.click:443"
    )
    assert urllib.parse.unquote(lines[0].split("#", 1)[1]) == (
        "🇩🇪 Frankfurt"
    )
    assert urllib.parse.unquote(lines[1].split("#", 1)[1]) == (
        "🇳🇱 Netherlands"
    )


def test_invalid_multi_node_json_keeps_legacy_single_node(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)
    module.VPN_NODES_JSON = "not-json"
    module.VPN_HOST = "legacy.example.com"
    module.VPN_WS_HOST = "legacy.example.com"
    module.VPN_SNI = "legacy.example.com"
    module.SERVER_DISPLAY_NAME = "Legacy"

    payload = module.build_subscription_payload(VALID_UUID)
    decoded = base64.b64decode(payload).decode("utf-8")
    lines = [line for line in decoded.splitlines() if line]

    assert len(lines) == 1
    assert lines[0].startswith(
        f"vless://{VALID_UUID}@legacy.example.com:443"
    )


def test_subscription_payload_contains_exactly_one_real_server_entry(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)
    module.VPN_HOST = "eu-vpn.example.com"
    module.VPN_WS_HOST = "eu-vpn.example.com"
    module.VPN_SNI = "eu-vpn.example.com"
    module.SERVER_DISPLAY_NAME = "🇫🇷 France #01"

    payload = module.build_subscription_payload(VALID_UUID)
    decoded = base64.b64decode(payload).decode("utf-8")
    lines = [line for line in decoded.splitlines() if line]

    assert len(lines) == 1
    assert lines[0].startswith(f"vless://{VALID_UUID}@eu-vpn.example.com:443")
    assert urllib.parse.unquote(lines[0].split("#", 1)[1]) == "🇫🇷 France #01"


def test_root_endpoint_exposes_clickable_telegram_and_profile_links(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)
    module.TELEGRAM_BOT_URL = "https://t.me/PresentVPNBot"
    module.PROFILE_WEB_PAGE_URL = "https://presentvpn.example.com"

    harness = HandlerHarness(module, path=f"/{VALID_UUID}").do_get()

    assert harness.responses == [200]
    assert harness.header_map["support-url"] == "https://t.me/PresentVPNBot"
    assert harness.header_map["announce-url"] == "https://t.me/PresentVPNBot"
    assert harness.header_map["profile-web-page-url"] == (
        "https://presentvpn.example.com"
    )


def test_expired_subscription_uses_expired_banner_and_keeps_exact_expiry(
    tmp_path,
):
    module = load_sub_server_without_startup()
    expire = 1_700_000_000
    write_allowed_metadata(
        module,
        tmp_path,
        expire=expire,
        status="expired",
    )
    module.TELEGRAM_BOT_URL = "https://t.me/PRESENT_VPN_BOT"
    module.PROFILE_WEB_PAGE_URL = "https://presentvpn.example.com"
    module.EXPIRED_ANNOUNCE_TEMPLATE = (
        "Subscription expired on {expires_at} • Renew via {telegram}"
    )

    harness = HandlerHarness(module, path=f"/{VALID_UUID}").do_get()

    announce = decode_base64_header(harness.header_map["announce"])

    assert harness.responses == [200]
    assert "Subscription expired on" in announce
    assert "@PRESENT_VPN_BOT" in announce
    assert harness.header_map["subscription-userinfo"].endswith(
        f"expire={expire}"
    )
    assert harness.header_map["support-url"] == "https://t.me/PRESENT_VPN_BOT"
    assert harness.header_map["profile-web-page-url"] == (
        "https://presentvpn.example.com"
    )

    decoded = base64.b64decode(harness.body).decode("utf-8")
    assert "127.0.0.1:9" in decoded


def test_health_endpoint_is_public_and_does_not_depend_on_metadata():
    module = load_sub_server_without_startup()

    harness = HandlerHarness(module, path="/healthz").do_get()

    assert harness.responses == [200]
    assert harness.header_map["Cache-Control"] == "no-store"
    assert harness.body == b"ok\n"


def test_unknown_or_forbidden_paths_return_expected_statuses(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)

    unknown = HandlerHarness(module, path="/unknown/path").do_get()
    assert unknown.responses == [404]
    assert unknown.body == b"not found"

    invalid_root_token = HandlerHarness(module, path="/not-a-uuid").do_get()
    assert invalid_root_token.responses == [404]
    assert invalid_root_token.body == b"not found"

    forbidden_root = HandlerHarness(module, path=f"/{UNKNOWN_UUID}").do_get()
    assert forbidden_root.responses == [403]
    assert forbidden_root.body == b"forbidden"

    forbidden_sub = HandlerHarness(module, path=f"/sub/{UNKNOWN_UUID}").do_get()
    assert forbidden_sub.responses == [403]
    assert forbidden_sub.body == b"forbidden"

    forbidden_connect = HandlerHarness(
        module,
        path=f"/connect/{UNKNOWN_UUID}?device=android",
    ).do_get()
    assert forbidden_connect.responses == [403]
    assert forbidden_connect.body == b"forbidden"


def test_default_server_display_name_is_current_frankfurt_node(monkeypatch):
    monkeypatch.delenv("VPN_SUBSCRIPTION_SERVER_NAME", raising=False)

    module = load_sub_server_without_startup()

    assert module.SERVER_DISPLAY_NAME == "🇩🇪 Frankfurt"

    link = module.build_vless_link(VALID_UUID)
    fragment = urllib.parse.unquote(link.split("#", 1)[1])

    assert fragment == "🇩🇪 Frankfurt"

def test_happ_advanced_banner_headers_with_provider_id(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(
        module,
        tmp_path,
        expire=2_000_000_000,
        status="active",
    )

    module.HAPP_PROVIDER_ID = "test-provider"
    module.HAPP_INFO_COLOR = "blue"
    module.HAPP_INFO_TEMPLATE = (
        "Manage subscription | {telegram} | "
        "Days left: {days_left} | Expires: {expires_at}"
    )
    module.HAPP_INFO_BUTTON_TEXT = "Telegram bot"
    module.TELEGRAM_BOT_URL = "https://t.me/PRESENT_VPN_BOT"

    headers = module.build_subscription_metadata_headers(VALID_UUID)

    assert headers["providerid"] == "test-provider"
    assert headers["sub-info-color"] == "blue"

    assert "Manage subscription" in headers["sub-info-text"]
    assert "@PRESENT_VPN_BOT" in headers["sub-info-text"]
    assert "Days left:" in headers["sub-info-text"]
    assert "Expires:" in headers["sub-info-text"]

    assert headers["sub-info-button-text"] == "Telegram bot"
    assert (
        headers["sub-info-button-link"]
        == "https://t.me/PRESENT_VPN_BOT"
    )

    assert headers["sub-expire"] == "1"
    assert (
        headers["sub-expire-button-link"]
        == "https://t.me/PRESENT_VPN_BOT"
    )

    # Existing thin announcement remains as fallback.
    assert "announce" in headers
    assert "subscription-userinfo" in headers
    assert "profile-title" in headers


def test_happ_advanced_banner_is_absent_without_provider_id(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)

    module.HAPP_PROVIDER_ID = ""

    headers = module.build_subscription_metadata_headers(VALID_UUID)

    assert "providerid" not in headers
    assert "sub-info-color" not in headers
    assert "sub-info-text" not in headers
    assert "sub-info-button-text" not in headers
    assert "sub-info-button-link" not in headers
    assert "sub-expire" not in headers
    assert "sub-expire-button-link" not in headers

    # Legacy/current subscription metadata keeps working.
    assert "profile-update-interval" in headers
    assert "subscription-userinfo" in headers
    assert "profile-title" in headers
    assert "announce" in headers
