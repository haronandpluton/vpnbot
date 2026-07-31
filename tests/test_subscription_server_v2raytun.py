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
                    "status": "active",
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


def decode_base64_header(value: str) -> str:
    assert value.startswith("base64:")
    return base64.b64decode(value[len("base64:"):]).decode("utf-8")


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


def test_connect_page_uses_v2raytun_deep_link_when_selected():
    module = load_sub_server_without_startup()
    subscription_url = f"https://connect.example.com/{VALID_UUID}"

    page = module.build_connect_page(
        client_uuid=VALID_UUID,
        device="ios",
        subscription_url=subscription_url,
        client="v2raytun",
    )

    assert f"v2raytun://import/{subscription_url}" in page
    assert 'const CLIENT_SCHEME = "v2raytun"' in page
    assert "Trying to open v2RayTun" in page
    assert f'value="{subscription_url}"' in page

    assert 'id="openV2RayTunBtn"' not in page
    assert f"happ://add/{subscription_url}" not in page
    assert "/sub/" not in page


def test_happ_and_v2raytun_have_independent_auto_open_keys():
    module = load_sub_server_without_startup()
    subscription_url = f"https://connect.example.com/{VALID_UUID}"

    happ_page = module.build_connect_page(
        client_uuid=VALID_UUID,
        device="android",
        subscription_url=subscription_url,
        client="happ",
    )

    v2raytun_page = module.build_connect_page(
        client_uuid=VALID_UUID,
        device="android",
        subscription_url=subscription_url,
        client="v2raytun",
    )

    assert 'const CLIENT_SCHEME = "happ"' in happ_page
    assert 'const CLIENT_SCHEME = "v2raytun"' in v2raytun_page

    for page in (happ_page, v2raytun_page):
        assert (
            '"vpn_auto_open_" + CLIENT_SCHEME + "_" + SUBSCRIPTION_URL'
            in page
        )
        assert "location.href = DEEP_LINK" in page
        assert "sessionStorage" in page


def test_v2raytun_uses_existing_subscription_payload_without_raw_vless(
    tmp_path,
):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)

    module.PUBLIC_BASE_URL = "https://connect.example.com"
    module.VPN_HOST = "eu-vpn.example.com"
    module.VPN_WS_HOST = "eu-vpn.example.com"
    module.VPN_SNI = "eu-vpn.example.com"

    root = HandlerHarness(
        module,
        path=f"/{VALID_UUID}",
    ).do_get()

    connect = HandlerHarness(
        module,
        path=(
            f"/connect/{VALID_UUID}"
            "?device=ios&client=v2raytun"
        ),
    ).do_get()

    assert root.responses == [200]
    assert root.header_map["profile-update-interval"] == "1"
    assert decode_base64_header(root.header_map["profile-title"]) == (
        "PRESENT VPN 🎁"
    )
    assert "Days left:" in decode_base64_header(root.header_map["announce"])
    assert root.header_map["subscription-userinfo"].endswith(
        "expire=9999999999"
    )

    decoded = base64.b64decode(root.body).decode("utf-8")
    assert decoded.startswith(
        f"vless://{VALID_UUID}@eu-vpn.example.com:443"
    )

    assert connect.responses == [200]

    page = connect.body.decode("utf-8")

    assert (
        f"v2raytun://import/"
        f"https://connect.example.com/{VALID_UUID}"
        in page
    )

    assert f"vless://{VALID_UUID}@" not in page

def test_v2raytun_receives_branding_and_clickable_announce_headers(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)
    module.PROFILE_TITLE = "🎁 PRESENT VPN"
    module.TELEGRAM_BOT_URL = "https://t.me/PresentVPNBot"

    harness = HandlerHarness(module, path=f"/{VALID_UUID}").do_get()

    assert harness.responses == [200]
    assert decode_base64_header(harness.header_map["profile-title"]) == (
        "🎁 PRESENT VPN"
    )
    assert harness.header_map["announce-url"] == "https://t.me/PresentVPNBot"
    announce = decode_base64_header(harness.header_map["announce"])
    assert "@PresentVPNBot" in announce
    assert "Days left:" in announce


def test_v2raytun_receives_expired_announcement_and_exact_expiry(tmp_path):
    module = load_sub_server_without_startup()
    meta_file = tmp_path / "subscriptions_meta.json"
    expire = 1_700_000_000
    meta_file.write_text(
        json.dumps(
            {
                VALID_UUID: {
                    "status": "expired",
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
    module.TELEGRAM_BOT_URL = "https://t.me/PRESENT_VPN_BOT"
    module.EXPIRED_ANNOUNCE_TEMPLATE = (
        "Subscription expired on {expires_at} • Renew via {telegram}"
    )

    harness = HandlerHarness(module, path=f"/{VALID_UUID}").do_get()

    announce = decode_base64_header(harness.header_map["announce"])

    assert harness.responses == [200]
    assert "Subscription expired on" in announce
    assert "@PRESENT_VPN_BOT" in announce
    assert harness.header_map["announce-url"] == "https://t.me/PRESENT_VPN_BOT"
    assert harness.header_map["subscription-userinfo"].endswith(
        f"expire={expire}"
    )


def test_connect_endpoint_routes_explicit_v2raytun_client(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)
    module.PUBLIC_BASE_URL = "https://connect.example.com"

    harness = HandlerHarness(
        module,
        path=(
            f"/connect/{VALID_UUID}"
            "?device=android&client=v2raytun"
        ),
    ).do_get()

    assert harness.responses == [200]

    page = harness.body.decode("utf-8")

    assert (
        f"v2raytun://import/"
        f"https://connect.example.com/{VALID_UUID}"
        in page
    )
    assert 'const CLIENT_SCHEME = "v2raytun"' in page
    assert f"happ://add/https://connect.example.com/{VALID_UUID}" not in page


def test_connect_endpoint_rejects_unknown_client(tmp_path):
    module = load_sub_server_without_startup()
    write_allowed_metadata(module, tmp_path)

    harness = HandlerHarness(
        module,
        path=(
            f"/connect/{VALID_UUID}"
            "?device=android&client=unknown"
        ),
    ).do_get()

    assert harness.responses == [400]
    assert harness.header_map["Content-Type"] == (
        "text/plain; charset=utf-8"
    )
    assert harness.header_map["Cache-Control"] == "no-store"
    assert harness.header_map["Connection"] == "close"
    assert harness.body == b"unsupported client"
    assert harness.handler.close_connection is True
