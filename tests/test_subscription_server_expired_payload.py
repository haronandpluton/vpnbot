from __future__ import annotations

import base64
import io
import json
import types
from pathlib import Path


SUB_SERVER_PATH = Path("deploy/vpn-subscription/sub_server.py")
VALID_UUID = "33333333-3333-4333-8333-333333333333"


def load_sub_server_without_startup():
    source = SUB_SERVER_PATH.read_text(encoding="utf-8")
    prefix = source.split('\nif __name__ == "__main__":', 1)[0]
    module = types.ModuleType("sub_server_expired_payload_under_test")
    exec(compile(prefix, str(SUB_SERVER_PATH), "exec"), module.__dict__)
    return module


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
        self.handler.end_headers = self.end_headers

    def send_response(self, code: int) -> None:
        self.responses.append(code)

    def send_header(self, key: str, value: str) -> None:
        self.headers.append((key, value))

    def end_headers(self) -> None:
        pass

    def do_get(self):
        self.handler.do_GET()
        return self

    @property
    def body(self) -> bytes:
        return self.handler.wfile.getvalue()

    @property
    def header_map(self) -> dict[str, str]:
        return dict(self.headers)


def write_meta(module, tmp_path, expire: int) -> None:
    module.SUBSCRIPTIONS_META_FILE = tmp_path / "subscriptions_meta.json"
    module.SUBSCRIPTIONS_META_FILE.write_text(
        json.dumps(
            {
                VALID_UUID: {
                    "upload": 0,
                    "download": 0,
                    "total": 0,
                    "expire": expire,
                }
            }
        ),
        encoding="utf-8",
    )


def decode_payload(payload: bytes) -> str:
    return base64.b64decode(payload).decode("utf-8")


def test_expire_zero_is_treated_as_unknown_not_expired(tmp_path):
    module = load_sub_server_without_startup()
    write_meta(module, tmp_path, expire=0)

    assert module.is_subscription_expired(VALID_UUID, now=1784603873) is False


def test_positive_expire_in_past_is_expired(tmp_path):
    module = load_sub_server_without_startup()
    write_meta(module, tmp_path, expire=100)

    assert module.is_subscription_expired(VALID_UUID, now=101) is True


def test_positive_expire_in_future_is_not_expired(tmp_path):
    module = load_sub_server_without_startup()
    write_meta(module, tmp_path, expire=200)

    assert module.is_subscription_expired(VALID_UUID, now=101) is False


def test_expired_payload_contains_clear_happ_stub_profile(tmp_path):
    module = load_sub_server_without_startup()
    write_meta(module, tmp_path, expire=100)

    payload = module.build_subscription_payload(VALID_UUID)
    decoded = decode_payload(payload)

    assert decoded.startswith(f"vless://{VALID_UUID}@127.0.0.1:9")
    assert "security=none" in decoded
    assert "type=tcp" in decoded
    assert "#❌ Подписка закончилась — продлите в Telegram" in decoded


def test_active_payload_contains_real_vless_profile(tmp_path):
    module = load_sub_server_without_startup()
    module.VPN_HOST = "vpn.example.com"
    module.VPN_WS_HOST = "vpn.example.com"
    module.VPN_SNI = "vpn.example.com"
    write_meta(module, tmp_path, expire=9999999999)

    payload = module.build_subscription_payload(VALID_UUID)
    decoded = decode_payload(payload)

    assert decoded.startswith(f"vless://{VALID_UUID}@vpn.example.com:443")
    assert "security=tls" in decoded
    assert "type=ws" in decoded
    assert "127.0.0.1:9" not in decoded


def test_root_endpoint_returns_expired_stub_when_metadata_expired(tmp_path):
    module = load_sub_server_without_startup()
    module.VPN_HOST = "vpn.example.com"
    module.VPN_WS_HOST = "vpn.example.com"
    module.VPN_SNI = "vpn.example.com"
    write_meta(module, tmp_path, expire=100)

    harness = HandlerHarness(module, path=f"/{VALID_UUID}").do_get()

    assert harness.responses == [200]
    assert harness.header_map["subscription-userinfo"] == (
        "upload=0; download=0; total=0; expire=100"
    )
    assert int(harness.header_map["Content-Length"]) == len(harness.body)

    decoded = decode_payload(harness.body)
    assert decoded.startswith(f"vless://{VALID_UUID}@127.0.0.1:9")
    assert "Подписка закончилась" in decoded


def test_sub_fallback_endpoint_returns_expired_stub_when_metadata_expired(tmp_path):
    module = load_sub_server_without_startup()
    module.VPN_HOST = "vpn.example.com"
    module.VPN_WS_HOST = "vpn.example.com"
    module.VPN_SNI = "vpn.example.com"
    write_meta(module, tmp_path, expire=100)

    harness = HandlerHarness(module, path=f"/sub/{VALID_UUID}").do_get()

    assert harness.responses == [200]
    assert harness.header_map["subscription-userinfo"] == (
        "upload=0; download=0; total=0; expire=100"
    )
    assert int(harness.header_map["Content-Length"]) == len(harness.body)

    decoded = decode_payload(harness.body)
    assert decoded.startswith(f"vless://{VALID_UUID}@127.0.0.1:9")
    assert "Подписка закончилась" in decoded