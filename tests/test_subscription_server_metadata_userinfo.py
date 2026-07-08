from __future__ import annotations

import base64
import io
import json
import os
import types
from pathlib import Path


SUB_SERVER_PATH = Path("deploy/vpn-subscription/sub_server.py")
VALID_UUID = "22222222-2222-4222-8222-222222222222"


def load_sub_server_without_startup():
    source = SUB_SERVER_PATH.read_text(encoding="utf-8")
    prefix = source.split('\nif __name__ == "__main__":', 1)[0]
    module = types.ModuleType("sub_server_metadata_under_test")
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


def test_load_subscriptions_meta_returns_empty_dict_when_file_is_missing(tmp_path):
    module = load_sub_server_without_startup()
    module.SUBSCRIPTIONS_META_FILE = tmp_path / "missing.json"

    assert module.load_subscriptions_meta() == {}


def test_load_subscriptions_meta_returns_empty_dict_for_invalid_json(tmp_path):
    module = load_sub_server_without_startup()
    meta_file = tmp_path / "subscriptions_meta.json"
    meta_file.write_text("{broken-json", encoding="utf-8")
    module.SUBSCRIPTIONS_META_FILE = meta_file

    assert module.load_subscriptions_meta() == {}


def test_load_subscriptions_meta_keeps_last_good_data_during_partial_write(tmp_path):
    module = load_sub_server_without_startup()
    meta_file = tmp_path / "subscriptions_meta.json"
    expected = {
        VALID_UUID: {
            "upload": 0,
            "download": 0,
            "total": 0,
            "expire": 1784603873,
        }
    }
    meta_file.write_text(json.dumps(expected), encoding="utf-8")
    module.SUBSCRIPTIONS_META_FILE = meta_file

    assert module.load_subscriptions_meta() == expected

    previous_mtime = meta_file.stat().st_mtime_ns
    meta_file.write_text("{partial", encoding="utf-8")
    os.utime(meta_file, ns=(previous_mtime + 1_000_000, previous_mtime + 1_000_000))

    assert module.load_subscriptions_meta() == expected


def test_subscription_userinfo_uses_exported_metadata_values(tmp_path):
    module = load_sub_server_without_startup()
    meta_file = tmp_path / "subscriptions_meta.json"
    meta_file.write_text(
        json.dumps(
            {
                VALID_UUID: {
                    "upload": 100,
                    "download": 200,
                    "total": 0,
                    "expire": 1784603873,
                }
            }
        ),
        encoding="utf-8",
    )
    module.SUBSCRIPTIONS_META_FILE = meta_file

    assert module.build_subscription_userinfo(VALID_UUID) == (
        "upload=100; download=200; total=0; expire=1784603873"
    )


def test_subscription_userinfo_falls_back_to_zeroes_for_missing_uuid(tmp_path):
    module = load_sub_server_without_startup()
    meta_file = tmp_path / "subscriptions_meta.json"
    meta_file.write_text("{}", encoding="utf-8")
    module.SUBSCRIPTIONS_META_FILE = meta_file

    assert module.build_subscription_userinfo(VALID_UUID) == (
        "upload=0; download=0; total=0; expire=0"
    )


def test_subscription_userinfo_sanitizes_invalid_metadata_values(tmp_path):
    module = load_sub_server_without_startup()
    meta_file = tmp_path / "subscriptions_meta.json"
    meta_file.write_text(
        json.dumps(
            {
                VALID_UUID: {
                    "upload": "bad",
                    "download": None,
                    "total": "0",
                    "expire": "1784603873",
                }
            }
        ),
        encoding="utf-8",
    )
    module.SUBSCRIPTIONS_META_FILE = meta_file

    assert module.build_subscription_userinfo(VALID_UUID) == (
        "upload=0; download=0; total=0; expire=1784603873"
    )


def test_root_subscription_endpoint_sends_subscription_userinfo_header(tmp_path):
    module = load_sub_server_without_startup()
    module.VPN_HOST = "vpn.example.com"
    module.VPN_WS_HOST = "vpn.example.com"
    module.VPN_SNI = "vpn.example.com"
    module.SUBSCRIPTIONS_META_FILE = tmp_path / "subscriptions_meta.json"
    module.SUBSCRIPTIONS_META_FILE.write_text(
        json.dumps(
            {
                VALID_UUID: {
                    "upload": 0,
                    "download": 0,
                    "total": 0,
                    "expire": 1784603873,
                }
            }
        ),
        encoding="utf-8",
    )

    harness = HandlerHarness(module, path=f"/{VALID_UUID}").do_get()

    assert harness.responses == [200]
    assert harness.header_map["profile-update-interval"] == "1"
    assert harness.header_map["subscription-userinfo"] == (
        "upload=0; download=0; total=0; expire=1784603873"
    )
    assert int(harness.header_map["Content-Length"]) == len(harness.body)

    decoded = base64.b64decode(harness.body).decode("utf-8")
    assert decoded.startswith(f"vless://{VALID_UUID}@vpn.example.com:443")


def test_sub_fallback_endpoint_sends_subscription_userinfo_header(tmp_path):
    module = load_sub_server_without_startup()
    module.VPN_HOST = "vpn.example.com"
    module.VPN_WS_HOST = "vpn.example.com"
    module.VPN_SNI = "vpn.example.com"
    module.SUBSCRIPTIONS_META_FILE = tmp_path / "subscriptions_meta.json"
    module.SUBSCRIPTIONS_META_FILE.write_text(
        json.dumps(
            {
                VALID_UUID: {
                    "upload": 0,
                    "download": 0,
                    "total": 0,
                    "expire": 1784603873,
                }
            }
        ),
        encoding="utf-8",
    )

    harness = HandlerHarness(module, path=f"/sub/{VALID_UUID}").do_get()

    assert harness.responses == [200]
    assert harness.header_map["profile-update-interval"] == "1"
    assert harness.header_map["subscription-userinfo"] == (
        "upload=0; download=0; total=0; expire=1784603873"
    )
    assert int(harness.header_map["Content-Length"]) == len(harness.body)

    decoded = base64.b64decode(harness.body).decode("utf-8")
    assert decoded.startswith(f"vless://{VALID_UUID}@vpn.example.com:443")