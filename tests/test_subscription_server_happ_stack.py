from __future__ import annotations

import base64
import io
import types
from pathlib import Path


SUB_SERVER_PATH = Path("deploy/vpn-subscription/sub_server.py")
VALID_UUID = "11111111-1111-4111-8111-111111111111"


def load_sub_server_without_startup():
    source = SUB_SERVER_PATH.read_text(encoding="utf-8")
    prefix = source.split("\ncontext = ssl.SSLContext", 1)[0]
    module = types.ModuleType("sub_server_under_test")
    exec(compile(prefix, str(SUB_SERVER_PATH), "exec"), module.__dict__)
    return module


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


def test_subscription_server_source_uses_threaded_https_server_without_global_socket_wrap():
    source = SUB_SERVER_PATH.read_text(encoding="utf-8")

    assert "class BetterThreadingHTTPServer(ThreadingHTTPServer):" in source
    assert "request_queue_size = 256" in source
    assert "daemon_threads = True" in source
    assert "class ThreadedHTTPSServer(BetterThreadingHTTPServer):" in source
    assert "def process_request_thread(self, request, client_address):" in source
    assert "ssl_context.wrap_socket(" in source
    assert "httpd = ThreadedHTTPSServer((HOST, PORT), Handler, context)" in source
    assert "httpd.socket = context.wrap_socket" not in source


def test_load_tokens_ignores_empty_lines_comments_and_whitespace(tmp_path):
    module = load_sub_server_without_startup()
    tokens_file = tmp_path / "tokens.txt"
    tokens_file.write_text(
        "\n"
        "# comment\n"
        " token-1 \n"
        "\n"
        "token-2\n",
        encoding="utf-8",
    )
    module.TOKENS_FILE = tokens_file

    assert module.load_tokens() == {"token-1", "token-2"}


def test_allowed_token_accepts_configured_tokens_and_uuid_tokens(tmp_path):
    module = load_sub_server_without_startup()
    tokens_file = tmp_path / "tokens.txt"
    tokens_file.write_text("configured-token\n", encoding="utf-8")
    module.TOKENS_FILE = tokens_file

    assert module.is_allowed_token("configured-token") is True
    assert module.is_allowed_token(VALID_UUID) is True
    assert module.is_allowed_token("not-configured-not-uuid") is False


def test_vless_link_contains_tls_websocket_happ_compatible_parameters():
    module = load_sub_server_without_startup()
    module.DOMAIN = "vpn.example.com"
    module.VPN_PORT = 443
    module.WS_PATH = "/ws-test"

    link = module.build_vless_link(VALID_UUID)

    assert link.startswith(f"vless://{VALID_UUID}@vpn.example.com:443?")
    assert "security=tls" in link
    assert "type=ws" in link
    assert "path=%2Fws-test" in link
    assert "host=vpn.example.com" in link
    assert "sni=vpn.example.com" in link
    assert "fp=chrome" in link
    assert "alpn=http%2F1.1" in link
    assert link.endswith("#vpn-11111111")


def test_subscription_url_uses_root_uuid_endpoint_not_sub_path():
    module = load_sub_server_without_startup()
    module.PUBLIC_BASE_URL = "https://vpn.example.com:2097"

    assert module.build_subscription_url(VALID_UUID) == (
        f"https://vpn.example.com:2097/{VALID_UUID}"
    )
    assert "/sub/" not in module.build_subscription_url(VALID_UUID)


def test_connect_page_contains_happ_add_deep_link_copy_fallback_and_once_guard():
    module = load_sub_server_without_startup()
    subscription_url = f"https://vpn.example.com:2097/{VALID_UUID}"

    page = module.build_connect_page(
        client_uuid=VALID_UUID,
        device="android",
        subscription_url=subscription_url,
    )

    assert f"happ://add/{subscription_url}" in page
    assert f'value="{subscription_url}"' in page
    assert "sessionStorage" in page
    assert "vpn_auto_open_" in page
    assert "setTimeout(function ()" in page
    assert "location.href = DEEP_LINK" in page
    assert "Открыть вручную" in page
    assert "Копировать" in page
    assert "/sub/" not in page


def test_root_subscription_endpoint_returns_base64_vless_and_required_headers():
    module = load_sub_server_without_startup()
    module.DOMAIN = "vpn.example.com"
    module.PUBLIC_BASE_URL = "https://vpn.example.com:2097"

    harness = HandlerHarness(module, path=f"/{VALID_UUID}").do_get()

    assert harness.responses == [200]
    assert harness.header_map["Content-Type"] == "text/plain; charset=utf-8"
    assert harness.header_map["profile-update-interval"] == "1"
    assert harness.header_map["Cache-Control"] == "no-store"
    assert harness.header_map["Connection"] == "close"
    assert int(harness.header_map["Content-Length"]) == len(harness.body)
    assert harness.handler.close_connection is True

    decoded = base64.b64decode(harness.body).decode("utf-8")
    assert decoded.startswith(f"vless://{VALID_UUID}@vpn.example.com:443")
    assert decoded.endswith("\n")


def test_sub_fallback_endpoint_returns_same_subscription_payload_and_headers():
    module = load_sub_server_without_startup()
    module.DOMAIN = "vpn.example.com"

    harness = HandlerHarness(module, path=f"/sub/{VALID_UUID}").do_get()

    assert harness.responses == [200]
    assert harness.header_map["Content-Type"] == "text/plain; charset=utf-8"
    assert harness.header_map["profile-update-interval"] == "1"
    assert harness.header_map["Cache-Control"] == "no-store"
    assert harness.header_map["Connection"] == "close"
    assert int(harness.header_map["Content-Length"]) == len(harness.body)

    decoded = base64.b64decode(harness.body).decode("utf-8")
    assert decoded.startswith(f"vless://{VALID_UUID}@vpn.example.com:443")


def test_connect_endpoint_returns_html_setup_page_with_safe_headers():
    module = load_sub_server_without_startup()
    module.DOMAIN = "vpn.example.com"
    module.PUBLIC_BASE_URL = "https://vpn.example.com:2097"

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
    assert "Устройство: <b>ios</b>" in page
    assert f"happ://add/https://vpn.example.com:2097/{VALID_UUID}" in page
    assert f'value="https://vpn.example.com:2097/{VALID_UUID}"' in page
    assert "sessionStorage" in page


def test_unknown_or_forbidden_paths_return_expected_statuses(tmp_path):
    module = load_sub_server_without_startup()
    tokens_file = tmp_path / "tokens.txt"
    tokens_file.write_text("allowed-token\n", encoding="utf-8")
    module.TOKENS_FILE = tokens_file

    unknown = HandlerHarness(module, path="/unknown/path").do_get()
    assert unknown.responses == [404]
    assert unknown.body == b"not found"

    invalid_root_token = HandlerHarness(module, path="/not-configured-not-uuid").do_get()
    assert invalid_root_token.responses == [404]
    assert invalid_root_token.body == b"not found"

    forbidden_sub = HandlerHarness(module, path="/sub/not-configured-not-uuid").do_get()
    assert forbidden_sub.responses == [403]
    assert forbidden_sub.body == b"forbidden"

    forbidden_connect = HandlerHarness(
        module,
        path="/connect/not-configured-not-uuid?device=android",
    ).do_get()
    assert forbidden_connect.responses == [403]
    assert forbidden_connect.body == b"forbidden"