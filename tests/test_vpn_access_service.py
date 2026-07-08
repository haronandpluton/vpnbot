from __future__ import annotations

from uuid import UUID

import pytest

import app.services.vpn_access_service as vpn_access_module
from app.services.vpn_access_service import (
    VpnAccessResult,
    VpnAccessService,
    build_client_email,
    build_connect_url,
    build_subscription_url,
)
from app.services.xui_client import XuiClientError


class FakeXuiClient:
    def __init__(self, *, fail_create: bool = False) -> None:
        self.fail_create = fail_create
        self.create_calls: list[dict] = []

    async def create_vless_client(
        self,
        *,
        client_uuid: str,
        email: str,
        device_limit: int,
        comment: str = "",
    ) -> None:
        self.create_calls.append(
            {
                "client_uuid": client_uuid,
                "email": email,
                "device_limit": device_limit,
                "comment": comment,
            }
        )

        if self.fail_create:
            raise XuiClientError("3x-ui client creation failed: test failure")


def make_service(
    *,
    xui_client: FakeXuiClient | None = None,
    public_base_url: str = "https://connect.presentvpn.click",
) -> VpnAccessService:
    service = VpnAccessService.__new__(VpnAccessService)
    service.xui_client = xui_client or FakeXuiClient()
    service.public_base_url = public_base_url
    return service


def test_build_subscription_url_uses_public_root_endpoint():
    assert (
        build_subscription_url("abc-123")
        == "https://connect.presentvpn.click/abc-123"
    )


def test_build_connect_url_uses_android_by_default():
    assert (
        build_connect_url("abc-123")
        == "https://connect.presentvpn.click/connect/abc-123?device=android"
    )


def test_build_connect_url_allows_explicit_device():
    assert (
        build_connect_url("abc-123", device="ios")
        == "https://connect.presentvpn.click/connect/abc-123?device=ios"
    )




def test_build_urls_allow_explicit_public_gateway_and_strip_trailing_slash():
    assert build_subscription_url(
        "abc-123",
        public_base_url="https://gateway.example.com/",
    ) == "https://gateway.example.com/abc-123"
    assert build_connect_url(
        "abc-123",
        device="ios beta",
        public_base_url="https://gateway.example.com/",
    ) == "https://gateway.example.com/connect/abc-123?device=ios+beta"


def test_build_client_email_is_stable_and_uses_uuid_prefix():
    assert (
        build_client_email(
            user_id=777,
            client_uuid="12345678-1234-5678-1234-567812345678",
        )
        == "tg-777-12345678"
    )


@pytest.mark.asyncio
async def test_create_access_generates_uuid_creates_xui_client_once_and_returns_connect_url(
    monkeypatch,
):
    fixed_uuid = UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(vpn_access_module, "uuid4", lambda: fixed_uuid)

    xui_client = FakeXuiClient()
    service = make_service(xui_client=xui_client)

    result = await service.create_access(user_id=777, device_limit=2)

    assert isinstance(result, VpnAccessResult)
    assert result.uuid == "12345678-1234-5678-1234-567812345678"
    assert result.vpn_server_id is None
    assert (
        result.config_uri
        == "https://connect.presentvpn.click/connect/12345678-1234-5678-1234-567812345678?device=android"
    )
    assert xui_client.create_calls == [
        {
            "client_uuid": "12345678-1234-5678-1234-567812345678",
            "email": "tg-777-12345678",
            "device_limit": 2,
            "comment": "telegram user 777",
        }
    ]


@pytest.mark.asyncio
async def test_create_access_propagates_xui_error_and_returns_no_fake_success(
    monkeypatch,
):
    fixed_uuid = UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(vpn_access_module, "uuid4", lambda: fixed_uuid)

    xui_client = FakeXuiClient(fail_create=True)
    service = make_service(xui_client=xui_client)

    with pytest.raises(XuiClientError, match="3x-ui client creation failed"):
        await service.create_access(user_id=777, device_limit=2)

    assert xui_client.create_calls == [
        {
            "client_uuid": "12345678-1234-5678-1234-567812345678",
            "email": "tg-777-12345678",
            "device_limit": 2,
            "comment": "telegram user 777",
        }
    ]


@pytest.mark.asyncio
async def test_create_access_generates_different_uuid_for_each_new_access(
    monkeypatch,
):
    generated = iter(
        [
            UUID("11111111-1111-1111-1111-111111111111"),
            UUID("22222222-2222-2222-2222-222222222222"),
        ]
    )
    monkeypatch.setattr(vpn_access_module, "uuid4", lambda: next(generated))

    xui_client = FakeXuiClient()
    service = make_service(xui_client=xui_client)

    first = await service.create_access(user_id=1, device_limit=1)
    second = await service.create_access(user_id=1, device_limit=1)

    assert first.uuid == "11111111-1111-1111-1111-111111111111"
    assert second.uuid == "22222222-2222-2222-2222-222222222222"
    assert len(xui_client.create_calls) == 2
    assert xui_client.create_calls[0]["email"] == "tg-1-11111111"
    assert xui_client.create_calls[1]["email"] == "tg-1-22222222"


@pytest.mark.asyncio
async def test_extend_access_preserves_existing_uuid_and_does_not_create_xui_client():
    xui_client = FakeXuiClient()
    service = make_service(xui_client=xui_client)

    result = await service.extend_access(
        uuid="existing-uuid",
        device_limit=3,
    )

    assert result == VpnAccessResult(
        uuid="existing-uuid",
        vpn_server_id=None,
        config_uri="https://connect.presentvpn.click/connect/existing-uuid?device=android",
    )
    assert xui_client.create_calls == []


@pytest.mark.asyncio
async def test_get_config_returns_existing_connect_url_without_creating_or_extending_access():
    xui_client = FakeXuiClient()
    service = make_service(xui_client=xui_client)

    config_uri = await service.get_config(
        uuid="existing-uuid",
        device_limit=3,
    )

    assert config_uri == "https://connect.presentvpn.click/connect/existing-uuid?device=android"
    assert xui_client.create_calls == []