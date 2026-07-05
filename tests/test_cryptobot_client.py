from __future__ import annotations

from decimal import Decimal

import pytest

import app.payment_adapters.cryptobot.client as client_module
from app.payment_adapters.cryptobot.client import CryptoBotAPIError, CryptoBotClient


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data=None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.json_data = json_data
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error

        return self.json_data


class FakeAsyncClient:
    instances: list["FakeAsyncClient"] = []
    queued_responses: list[FakeResponse] = []

    def __init__(self, *, timeout=None) -> None:
        self.timeout = timeout
        self.get_calls: list[dict] = []
        self.enter_count = 0
        self.exit_count = 0
        self.__class__.instances.append(self)

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_count += 1
        return False

    async def get(self, url: str, **kwargs):
        self.get_calls.append({"url": url, **kwargs})

        if not self.__class__.queued_responses:
            raise AssertionError(f"Unexpected GET: {url}")

        return self.__class__.queued_responses.pop(0)


@pytest.fixture(autouse=True)
def patch_async_client(monkeypatch):
    FakeAsyncClient.instances = []
    FakeAsyncClient.queued_responses = []
    monkeypatch.setattr(client_module.httpx, "AsyncClient", FakeAsyncClient)


def make_client(**overrides):
    values = {
        "api_url": "https://pay.crypt.bot/api/",
        "api_token": "token-123",
        "timeout_seconds": 12.5,
    }
    values.update(overrides)
    return CryptoBotClient(**values)


@pytest.mark.asyncio
async def test_get_rejects_empty_api_token_before_http_request():
    client = make_client(api_token="   ")

    with pytest.raises(CryptoBotAPIError, match="CRYPTOBOT_API_TOKEN is empty"):
        await client._get("getMe")

    assert FakeAsyncClient.instances == []


@pytest.mark.asyncio
async def test_get_strips_api_url_sends_headers_timeout_and_returns_result():
    FakeAsyncClient.queued_responses = [
        FakeResponse(json_data={"ok": True, "result": {"app": "PresentVPN"}})
    ]
    client = make_client(api_url="https://pay.crypt.bot/api///", timeout_seconds=7.0)

    result = await client._get("getMe", {"param": "value"})

    assert result == {"app": "PresentVPN"}
    fake_http = FakeAsyncClient.instances[0]
    assert fake_http.timeout == 7.0
    assert fake_http.enter_count == 1
    assert fake_http.exit_count == 1
    assert fake_http.get_calls == [
        {
            "url": "https://pay.crypt.bot/api/getMe",
            "params": {"param": "value"},
            "headers": {
                "Crypto-Pay-API-Token": "token-123",
                "Accept": "application/json",
                "User-Agent": "PresentVPN/1.0",
            },
        }
    ]


@pytest.mark.asyncio
async def test_get_uses_empty_params_dict_when_params_are_not_provided():
    FakeAsyncClient.queued_responses = [
        FakeResponse(json_data={"ok": True, "result": "ok"})
    ]
    client = make_client()

    result = await client._get("getMe")

    assert result == "ok"
    assert FakeAsyncClient.instances[0].get_calls[0]["params"] == {}


@pytest.mark.asyncio
async def test_get_rejects_non_json_response_with_http_status():
    FakeAsyncClient.queued_responses = [
        FakeResponse(status_code=502, json_error=ValueError("bad json"))
    ]
    client = make_client()

    with pytest.raises(
        CryptoBotAPIError,
        match="CryptoBot returned non-JSON response: HTTP 502",
    ):
        await client._get("getMe")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "payload"),
    [
        (500, {"ok": True, "result": {"ignored": True}}),
        (200, {"ok": False, "error": "APP_TOKEN_INVALID"}),
        (200, {"result": {"ok_key_missing": True}}),
    ],
)
async def test_get_rejects_http_error_or_non_ok_payload(status_code, payload):
    FakeAsyncClient.queued_responses = [
        FakeResponse(status_code=status_code, json_data=payload)
    ]
    client = make_client()

    with pytest.raises(CryptoBotAPIError) as exc_info:
        await client._get("getMe")

    assert f"CryptoBot API error: HTTP {status_code}; payload={payload!r}" in str(
        exc_info.value
    )


@pytest.mark.asyncio
async def test_create_invoice_sends_expected_cryptobot_params_and_returns_dict():
    invoice = {
        "invoice_id": 123,
        "pay_url": "https://t.me/CryptoBot?start=invoice-123",
    }
    FakeAsyncClient.queued_responses = [
        FakeResponse(json_data={"ok": True, "result": invoice})
    ]
    client = make_client()

    result = await client.create_invoice(
        asset="USDT",
        amount=Decimal("4.00"),
        description="PresentVPN order #23",
        payload="order:23",
        expires_in=900,
    )

    assert result == invoice
    assert FakeAsyncClient.instances[0].get_calls == [
        {
            "url": "https://pay.crypt.bot/api/createInvoice",
            "params": {
                "asset": "USDT",
                "amount": "4.00",
                "description": "PresentVPN order #23",
                "payload": "order:23",
                "expires_in": "900",
                "allow_comments": "false",
                "allow_anonymous": "false",
            },
            "headers": {
                "Crypto-Pay-API-Token": "token-123",
                "Accept": "application/json",
                "User-Agent": "PresentVPN/1.0",
            },
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, [], "invoice"])
async def test_create_invoice_rejects_unexpected_result_structure(result):
    FakeAsyncClient.queued_responses = [
        FakeResponse(json_data={"ok": True, "result": result})
    ]
    client = make_client()

    with pytest.raises(CryptoBotAPIError) as exc_info:
        await client.create_invoice(
            asset="USDT",
            amount=Decimal("4.00"),
            description="desc",
            payload="order:23",
            expires_in=900,
        )

    assert f"Unexpected createInvoice result: {result!r}" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_invoice_returns_matching_item_from_dict_items_result():
    matching = {"invoice_id": 23, "status": "paid"}
    FakeAsyncClient.queued_responses = [
        FakeResponse(
            json_data={
                "ok": True,
                "result": {
                    "items": [
                        {"invoice_id": 22, "status": "active"},
                        matching,
                    ]
                },
            }
        )
    ]
    client = make_client()

    result = await client.get_invoice("23")

    assert result == matching
    assert FakeAsyncClient.instances[0].get_calls[0]["params"] == {
        "invoice_ids": "23"
    }


@pytest.mark.asyncio
async def test_get_invoice_returns_first_item_from_dict_items_when_exact_id_not_found():
    first = {"invoice_id": 22, "status": "active"}
    FakeAsyncClient.queued_responses = [
        FakeResponse(
            json_data={
                "ok": True,
                "result": {"items": [first, {"invoice_id": 24}]},
            }
        )
    ]
    client = make_client()

    assert await client.get_invoice(23) == first


@pytest.mark.asyncio
async def test_get_invoice_returns_none_when_dict_items_are_empty():
    FakeAsyncClient.queued_responses = [
        FakeResponse(json_data={"ok": True, "result": {"items": []}})
    ]
    client = make_client()

    assert await client.get_invoice(23) is None


@pytest.mark.asyncio
async def test_get_invoice_returns_direct_dict_when_invoice_id_matches():
    invoice = {"invoice_id": "23", "status": "paid"}
    FakeAsyncClient.queued_responses = [
        FakeResponse(json_data={"ok": True, "result": invoice})
    ]
    client = make_client()

    assert await client.get_invoice(23) == invoice


@pytest.mark.asyncio
async def test_get_invoice_returns_matching_item_from_list_result():
    matching = {"invoice_id": "23", "status": "paid"}
    FakeAsyncClient.queued_responses = [
        FakeResponse(
            json_data={
                "ok": True,
                "result": [{"invoice_id": "22"}, matching],
            }
        )
    ]
    client = make_client()

    assert await client.get_invoice(23) == matching


@pytest.mark.asyncio
async def test_get_invoice_returns_first_item_from_list_when_exact_id_not_found():
    first = {"invoice_id": "22"}
    FakeAsyncClient.queued_responses = [
        FakeResponse(json_data={"ok": True, "result": [first, {"invoice_id": "24"}]})
    ]
    client = make_client()

    assert await client.get_invoice(23) == first


@pytest.mark.asyncio
async def test_get_invoice_returns_none_when_list_result_is_empty():
    FakeAsyncClient.queued_responses = [
        FakeResponse(json_data={"ok": True, "result": []})
    ]
    client = make_client()

    assert await client.get_invoice(23) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, "invoice", 123])
async def test_get_invoice_rejects_unexpected_result_structure(result):
    FakeAsyncClient.queued_responses = [
        FakeResponse(json_data={"ok": True, "result": result})
    ]
    client = make_client()

    with pytest.raises(CryptoBotAPIError) as exc_info:
        await client.get_invoice(23)

    assert f"Unexpected getInvoices result: {result!r}" in str(exc_info.value)