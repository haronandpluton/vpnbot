from __future__ import annotations

import base64
import io
import json
import types
from pathlib import Path


SUB_SERVER_PATH = Path("deploy/vpn-subscription/sub_server.py")
VALID_UUID = "11111111-1111-4111-8111-111111111111"


def load_sub_server_without_startup():
    source = SUB_SERVER_PATH.read_text(encoding="utf-8")
    prefix = source.split('\nif __name__ == "__main__":', 1)[0]
    module = types.ModuleType("sub_server_v2raytun_under_test")
    exec(compile(prefix, str(SUB_SERVER_PATH), "exec"), module.__dict__)
    return module


def write_allowed_metadata(module, tmp_path) -> None:
    meta_file = tmp_path / "subscriptions_meta.json"
    meta_file.write_text(
        json.dumps(
            {
                VALID_UUID: {
                    "upload": 0,
                    "download": 0,
                    "total": 0,
                    "expire": 9999999999,
                }
            }
        ),
        encoding="utf-8",
    )
    module.SUBSCRIPTIONS_META_FILE = meta_file
    module._subscriptions_meta_cache = {}
    module._subscriptions_meta_last_seen_mtime_ns = None


class HandlerHarness:
    def __init__(self, module, *, path: str) -> None:
        self.handler = object.__new__(module.Handler)
        self.handler.path = path
        self.handler.wfile = io.BytesIO()
        self.handler.client_address = ("127.0.0.1", 12345)
        self.handler.close_connection = False
        self.responses: list[int] = []
        self.headers: list[tuple[str, str]] = []

        self.handler.send_response = self.send_response
        self.handler.send_header = self.send_header
        self.handler.end_headers = lambda: None

    def send_response(self, code: int) -> None:
        self.responses.append(code)

    def send_header(self, key: str, value: str) -> None:
        self.headers.append((key, value))

    def do_get(self):
        self.handler.do_GET()
        return self

    @property
    def body(self) -> bytes:
        return self.handler.wfile.getvalue()

    @property
    def header_map(self) -> dict[str, str]:
        return dict(self.headers)


def test_v2raytun_deep_link_imports_existing_root_subscription_url():
    module = load_sub_server_without_startup()
    subscription_url = f"https://connect.example.com/{VALID_UUID}"

    assert module.build_v2raytun_deep_link(subscription_url) == (
        f"v2raytun://import/{subscription_url}"
    )
    assert "/sub/" not in module.build_v2raytun_deep_link(subscription_url)


def test_connect_page_contains_v2raytun_button_for_same_subscription():
    module = load_sub_server_without_startup()
    subscription_url = f"https://connect.example.com/{VALID_UUID}"

    page = module.build_connect_page(
        client_uuid=VALID_UUID,
        device="ios",
        subscription_url=subscription_url,
    )

    assert f"v2raytun://import/{subscription_url}" in page
    assert 'id="openV2RayTunBtn"' in page
    assert "Open in v2RayTun" in page
    assert f'value="{subscription_url}"' in page
    assert f"v2raytun://import/https://connect.example.com/sub/{VALID_UUID}" not in page


def test_v2raytun_support_does_not_replace_happ_auto_open():
    module = load_sub_server_without_startup()
    subscription_url = f"https://connect.example.com/{VALID_UUID}"

    page = module.build_connect_page(
        client_uuid=VALID_UUID,
        device="android",
        subscription_url=subscription_url,
    )

    assert f"happ://add/{subscription_url}" in page
    assert 'const DEEP_LINK = "happ://add/' in page
    assert "location.href = DEEP_LINK" in page
    assert "sessionStorage" in page
    assert f"v2raytun://import/{subscription_url}" in page


def test_v2raytun_uses_existing_subscription_payload_without_raw_link_on_connect_page(
    tmp_path,
):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)
    module.PUBLIC_BASE_URL = "https://connect.example.com"
    module.VPN_HOST = "eu-vpn.example.com"
    module.VPN_WS_HOST = "eu-vpn.example.com"
    module.VPN_SNI = "eu-vpn.example.com"

    root = HandlerHarness(module, path=f"/{VALID_UUID}").do_get()
    connect = HandlerHarness(module, path=f"/connect/{VALID_UUID}?device=ios").do_get()

    assert root.responses == [200]
    assert root.header_map["profile-update-interval"] == "1"
    decoded = base64.b64decode(root.body).decode("utf-8")
    assert decoded.startswith(f"vless://{VALID_UUID}@eu-vpn.example.com:443")

    page = connect.body.decode("utf-8")
    assert f"v2raytun://import/https://connect.example.com/{VALID_UUID}" in page
    assert f"vless://{VALID_UUID}@" not in page
