from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from datetime import datetime, timezone
import app.services.xui_client as xui_module
from app.services.xui_client import (
    XuiClient,
    XuiClientError,
    XuiConfig,
    make_xui_client_from_settings,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = "",
        json_data=None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.json_data = json_data
        self.json_error = json_error
        self.raise_for_status_count = 0

    def json(self):
        if self.json_error is not None:
            raise self.json_error

        return self.json_data

    def raise_for_status(self) -> None:
        self.raise_for_status_count += 1

        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "HTTP error",
                request=httpx.Request("GET", "https://xui.example"),
                response=httpx.Response(self.status_code),
            )


class FakeAsyncClient:
    instances: list["FakeAsyncClient"] = []

    def __init__(self, *, timeout=None, follow_redirects=None) -> None:
        self.timeout = timeout
        self.follow_redirects = follow_redirects
        self.get_calls: list[str] = []
        self.post_calls: list[dict] = []
        self.get_responses: list[FakeResponse] = []
        self.post_responses: list[FakeResponse] = []
        self.enter_count = 0
        self.exit_count = 0
        self.__class__.instances.append(self)

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_count += 1
        return False

    async def get(self, url: str):
        self.get_calls.append(url)

        if not self.get_responses:
            raise AssertionError(f"Unexpected GET: {url}")

        return self.get_responses.pop(0)

    async def post(self, url: str, **kwargs):
        self.post_calls.append({"url": url, **kwargs})

        if not self.post_responses:
            raise AssertionError(f"Unexpected POST: {url}")

        return self.post_responses.pop(0)


@pytest.fixture(autouse=True)
def reset_fake_async_client():
    FakeAsyncClient.instances = []


def make_config(**overrides):
    values = {
        "base_url": "https://xui.example/",
        "username": "admin",
        "password": "secret",
        "inbound_id": 42,
    }
    values.update(overrides)
    return XuiConfig(**values)


def test_client_strips_trailing_slash_from_base_url():
    client = XuiClient(make_config(base_url="https://xui.example///"))

    assert client.base_url == "https://xui.example"
    assert client.config.inbound_id == 42


def test_validate_uuid_accepts_valid_uuid():
    XuiClient._validate_uuid("12345678-1234-5678-1234-567812345678")


def test_validate_uuid_rejects_invalid_uuid_with_clear_error():
    with pytest.raises(XuiClientError, match="invalid client uuid: not-a-uuid"):
        XuiClient._validate_uuid("not-a-uuid")


def test_extract_csrf_reads_content_attribute_from_html():
    assert (
        XuiClient._extract_csrf('<meta name="csrf-token" content="csrf-123">')
        == "csrf-123"
    )


def test_extract_csrf_rejects_html_without_token():
    with pytest.raises(XuiClientError, match="CSRF token not found"):
        XuiClient._extract_csrf("<html></html>")


def test_json_returns_dict_payload():
    response = FakeResponse(json_data={"success": True})

    assert XuiClient._json(response) == {"success": True}


def test_json_rejects_non_json_response_with_http_status():
    response = FakeResponse(status_code=502, json_error=ValueError("bad json"))

    with pytest.raises(
        XuiClientError,
        match="3x-ui returned non-json response: HTTP 502",
    ):
        XuiClient._json(response)


def test_json_rejects_json_array_structure():
    response = FakeResponse(json_data=["not", "dict"])

    with pytest.raises(XuiClientError, match="3x-ui returned invalid json structure"):
        XuiClient._json(response)


@pytest.mark.asyncio
async def test_login_fetches_initial_csrf_posts_credentials_and_returns_panel_csrf():
    client = XuiClient(make_config(base_url="https://xui.example/"))
    http_client = FakeAsyncClient()
    http_client.get_responses = [
        FakeResponse(text='<meta name="csrf-token" content="csrf-login">'),
        FakeResponse(text='<meta name="csrf-token" content="csrf-panel">'),
    ]
    http_client.post_responses = [FakeResponse(json_data={"success": True})]

    csrf = await client._login(http_client)

    assert csrf == "csrf-panel"
    assert http_client.get_calls == [
        "https://xui.example/",
        "https://xui.example/panel/",
    ]
    assert http_client.post_calls == [
        {
            "url": "https://xui.example/login",
            "data": {"username": "admin", "password": "secret"},
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-Token": "csrf-login",
            },
        }
    ]


@pytest.mark.asyncio
async def test_login_raises_when_login_response_is_not_successful():
    client = XuiClient(make_config())
    http_client = FakeAsyncClient()
    http_client.get_responses = [
        FakeResponse(text='<meta name="csrf-token" content="csrf-login">'),
    ]
    http_client.post_responses = [
        FakeResponse(json_data={"success": False, "msg": "bad credentials"})
    ]

    with pytest.raises(XuiClientError, match="3x-ui login failed: bad credentials"):
        await client._login(http_client)

    assert http_client.get_calls == ["https://xui.example/"]


@pytest.mark.asyncio
async def test_create_vless_client_builds_payload_and_posts_to_3xui(monkeypatch):
    monkeypatch.setattr(xui_module.secrets, "token_hex", lambda size: "subid-123")

    fake_http_client = FakeAsyncClient(timeout=20.0, follow_redirects=True)
    fake_http_client.post_responses = [FakeResponse(json_data={"success": True})]

    def fake_client_factory(*, timeout, follow_redirects):
        assert timeout == 20.0
        assert follow_redirects is True
        return fake_http_client

    monkeypatch.setattr(xui_module.httpx, "AsyncClient", fake_client_factory)

    async def fake_login(self, client):
        return "csrf-panel"

    monkeypatch.setattr(XuiClient, "_login", fake_login)

    client = XuiClient(make_config(base_url="https://xui.example/"))

    expires_at = datetime(
        2030,
        1,
        1,
        tzinfo=timezone.utc,
    )

    await client.create_vless_client(
        client_uuid="12345678-1234-5678-1234-567812345678",
        email="tg-7-12345678",
        device_limit=3,
        expires_at=expires_at,
        comment="telegram user 7",
    )

    assert fake_http_client.timeout == 20.0
    assert fake_http_client.follow_redirects is True
    assert fake_http_client.enter_count == 1
    assert fake_http_client.exit_count == 1
    assert fake_http_client.post_calls == [
        {
            "url": "https://xui.example/panel/api/clients/add",
            "json": {
                "client": {
                    "email": "tg-7-12345678",
                    "subId": "subid-123",
                    "id": "12345678-1234-5678-1234-567812345678",
                    "password": "",
                    "auth": "",
                    "flow": "",
                    "security": "auto",
                    "totalGB": 0,
                    "expiryTime": 1893456000000,
                    "limitIp": 3,
                    "tgId": 0,
                    "reset": 0,
                    "group": "",
                    "comment": "telegram user 7",
                    "enable": True,
                },
                "inboundIds": [42],
            },
            "headers": {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-Token": "csrf-panel",
            },
        }
    ]


@pytest.mark.asyncio
async def test_create_vless_client_rejects_3xui_unsuccessful_response(monkeypatch):
    async def fake_login(self, client):
        return "csrf-panel"

    monkeypatch.setattr(XuiClient, "_login", fake_login)

    client = XuiClient(make_config())
    fake_http_client = FakeAsyncClient(timeout=20.0, follow_redirects=True)
    fake_http_client.post_responses = [
        FakeResponse(json_data={"success": False, "msg": "duplicate email"})
    ]

    def fake_client_factory(*, timeout, follow_redirects):
        assert timeout == 20.0
        assert follow_redirects is True
        return fake_http_client

    monkeypatch.setattr(xui_module.httpx, "AsyncClient", fake_client_factory)

    with pytest.raises(
        XuiClientError,
        match="3x-ui client creation failed: duplicate email",
    ):
        await client.create_vless_client(
            client_uuid="12345678-1234-5678-1234-567812345678",
            email="tg-7-12345678",
            device_limit=1,
        )


def test_make_xui_client_from_settings_maps_settings_to_config():
    settings = SimpleNamespace(
        xui_base_url="https://xui.example///",
        xui_username="admin",
        xui_password="secret",
        xui_inbound_id=99,
    )

    client = make_xui_client_from_settings(settings)

    assert isinstance(client, XuiClient)
    assert client.base_url == "https://xui.example"
    assert client.config == XuiConfig(
        base_url="https://xui.example///",
        username="admin",
        password="secret",
        inbound_id=99,
    )

def test_expiry_time_ms_is_zero_when_expiry_is_not_configured():
    assert XuiClient._to_expiry_time_ms(None) == 0


def test_expiry_time_ms_converts_aware_datetime_to_unix_milliseconds():
    expires_at = datetime(
        2030,
        1,
        1,
        0,
        0,
        0,
        tzinfo=timezone.utc,
    )

    assert XuiClient._to_expiry_time_ms(expires_at) == 1893456000000


def test_expiry_time_ms_rejects_naive_datetime():
    expires_at = datetime(2030, 1, 1)

    with pytest.raises(
        XuiClientError,
        match="expires_at must be timezone-aware",
    ):
        XuiClient._to_expiry_time_ms(expires_at)