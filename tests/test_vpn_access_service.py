from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

import app.services.vpn_access_service as vpn_access_module
from app.services.vpn_access_service import (
    VpnAccessResult,
    VpnAccessService,
    build_client_email,
    build_connect_url,
    build_idempotent_uuid,
    build_subscription_url,
)
from app.services.xui_client import XuiClientError


class FakeXuiClient:
    def __init__(
        self,
        *,
        fail_create: bool = False,
        fail_update: bool = False,
        fail_enable: bool = False,
        fail_disable: bool = False,
    ) -> None:
        self.fail_create = fail_create
        self.fail_update = fail_update
        self.fail_enable = fail_enable
        self.fail_disable = fail_disable
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.enable_calls: list[str] = []
        self.disable_calls: list[str] = []

    async def create_vless_client(
            self,
            *,
            client_uuid: str,
            email: str,
            device_limit: int,
            expires_at: datetime | None = None,
            comment: str = "",
    ) -> None:
        self.create_calls.append(
            {
                "client_uuid": client_uuid,
                "email": email,
                "device_limit": device_limit,
                "expires_at": expires_at,
                "comment": comment,
            }
        )

        if self.fail_create:
            raise XuiClientError("3x-ui client creation failed: test failure")

    async def update_vless_client(
        self,
        *,
        client_uuid: str,
        device_limit: int,
        expires_at: datetime,
    ) -> None:
        self.update_calls.append(
            {
                "client_uuid": client_uuid,
                "device_limit": device_limit,
                "expires_at": expires_at,
            }
        )

        if self.fail_update:
            raise XuiClientError("3x-ui client update failed: test failure")

    async def enable_vless_client(self, *, client_uuid: str) -> None:
        self.enable_calls.append(client_uuid)
        if self.fail_enable:
            raise XuiClientError("3x-ui client enable failed: test failure")

    async def disable_vless_client(self, *, client_uuid: str) -> None:
        self.disable_calls.append(client_uuid)
        if self.fail_disable:
            raise XuiClientError("3x-ui client disable failed: test failure")


def make_service(
    *,
    xui_client: FakeXuiClient | None = None,
    xui_clients: list[FakeXuiClient] | None = None,
    public_base_url: str = "https://connect.presentvpn.click",
    uuid_secret: str = "test-vpn-uuid-secret",
) -> VpnAccessService:
    service = VpnAccessService.__new__(VpnAccessService)
    clients = xui_clients or [xui_client or FakeXuiClient()]
    service.xui_clients = clients
    service.xui_client = clients[0]
    service.public_base_url = public_base_url
    service.uuid_secret = uuid_secret
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


def test_build_idempotent_uuid_is_stable_and_secret_scoped():
    first = build_idempotent_uuid(
        secret="secret-a",
        idempotency_key="order:123",
    )
    second = build_idempotent_uuid(
        secret="secret-a",
        idempotency_key="order:123",
    )
    other_order = build_idempotent_uuid(
        secret="secret-a",
        idempotency_key="order:124",
    )
    other_secret = build_idempotent_uuid(
        secret="secret-b",
        idempotency_key="order:123",
    )

    assert first == second
    assert first != other_order
    assert first != other_secret
    assert str(UUID(first)) == first


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
            "expires_at": None,
        }
    ]

@pytest.mark.asyncio
async def test_create_access_forwards_expiration_to_xui_client(
    monkeypatch,
):
    fixed_uuid = UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(vpn_access_module, "uuid4", lambda: fixed_uuid)

    expires_at = datetime(
        2030,
        1,
        1,
        tzinfo=timezone.utc,
    )

    xui_client = FakeXuiClient()
    service = make_service(xui_client=xui_client)

    result = await service.create_access(
        user_id=777,
        device_limit=1,
        expires_at=expires_at,
    )

    assert result.uuid == "12345678-1234-5678-1234-567812345678"
    assert xui_client.create_calls == [
        {
            "client_uuid": "12345678-1234-5678-1234-567812345678",
            "email": "tg-777-12345678",
            "device_limit": 1,
            "expires_at": expires_at,
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
            "expires_at": None,
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
async def test_create_access_uses_same_retry_safe_uuid_on_all_configured_nodes():
    first_node = FakeXuiClient()
    second_node = FakeXuiClient()
    service = make_service(xui_clients=[first_node, second_node])

    first_result = await service.create_access(
        user_id=777,
        device_limit=2,
        idempotency_key="order:23",
    )
    second_result = await service.create_access(
        user_id=777,
        device_limit=2,
        idempotency_key="order:23",
    )

    assert first_result.uuid == second_result.uuid
    assert len(first_node.create_calls) == 2
    assert len(second_node.create_calls) == 2
    assert first_node.create_calls[0]["client_uuid"] == first_result.uuid
    assert second_node.create_calls[0]["client_uuid"] == first_result.uuid
    assert first_node.create_calls[0]["email"] == second_node.create_calls[0]["email"]


@pytest.mark.asyncio
async def test_create_access_stops_and_propagates_secondary_node_failure():
    first_node = FakeXuiClient()
    second_node = FakeXuiClient(fail_create=True)
    service = make_service(xui_clients=[first_node, second_node])

    with pytest.raises(XuiClientError, match="3x-ui client creation failed"):
        await service.create_access(
            user_id=777,
            device_limit=2,
            idempotency_key="order:23",
        )

    assert len(first_node.create_calls) == 1
    assert len(second_node.create_calls) == 1
    assert (
        first_node.create_calls[0]["client_uuid"]
        == second_node.create_calls[0]["client_uuid"]
    )


@pytest.mark.asyncio
async def test_extend_access_updates_expiry_on_all_configured_nodes():
    first_node = FakeXuiClient()
    second_node = FakeXuiClient()
    service = make_service(xui_clients=[first_node, second_node])
    expires_at = datetime(2030, 1, 1, tzinfo=timezone.utc)

    result = await service.extend_access(
        uuid="12345678-1234-5678-1234-567812345678",
        device_limit=3,
        expires_at=expires_at,
    )

    assert result == VpnAccessResult(
        uuid="12345678-1234-5678-1234-567812345678",
        vpn_server_id=None,
        config_uri=(
            "https://connect.presentvpn.click/connect/"
            "12345678-1234-5678-1234-567812345678?device=android"
        ),
    )
    expected = [
        {
            "client_uuid": "12345678-1234-5678-1234-567812345678",
            "device_limit": 3,
            "expires_at": expires_at,
        }
    ]
    assert first_node.update_calls == expected
    assert second_node.update_calls == expected
    assert first_node.create_calls == []
    assert second_node.create_calls == []


@pytest.mark.asyncio
async def test_extend_access_stops_and_propagates_secondary_node_failure():
    first_node = FakeXuiClient()
    second_node = FakeXuiClient(fail_update=True)
    service = make_service(xui_clients=[first_node, second_node])
    expires_at = datetime(2030, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(XuiClientError, match="3x-ui client update failed"):
        await service.extend_access(
            uuid="12345678-1234-5678-1234-567812345678",
            device_limit=3,
            expires_at=expires_at,
        )

    assert len(first_node.update_calls) == 1
    assert len(second_node.update_calls) == 1


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

@pytest.mark.asyncio
async def test_disable_access_disables_same_uuid_on_all_configured_nodes():
    first_node = FakeXuiClient()
    second_node = FakeXuiClient()
    service = make_service(xui_clients=[first_node, second_node])
    client_uuid = "12345678-1234-5678-1234-567812345678"

    result = await service.disable_access(client_uuid)

    assert result == VpnAccessResult(
        uuid=client_uuid,
        vpn_server_id=None,
        config_uri=(
            "https://connect.presentvpn.click/connect/"
            f"{client_uuid}?device=android"
        ),
    )
    assert first_node.disable_calls == [client_uuid]
    assert second_node.disable_calls == [client_uuid]
    assert first_node.enable_calls == []
    assert second_node.enable_calls == []


@pytest.mark.asyncio
async def test_enable_access_enables_same_uuid_on_all_configured_nodes():
    first_node = FakeXuiClient()
    second_node = FakeXuiClient()
    service = make_service(xui_clients=[first_node, second_node])
    client_uuid = "12345678-1234-5678-1234-567812345678"

    result = await service.enable_access(client_uuid)

    assert result.uuid == client_uuid
    assert first_node.enable_calls == [client_uuid]
    assert second_node.enable_calls == [client_uuid]
    assert first_node.disable_calls == []
    assert second_node.disable_calls == []


@pytest.mark.asyncio
async def test_disable_access_propagates_secondary_node_failure():
    first_node = FakeXuiClient()
    second_node = FakeXuiClient(fail_disable=True)
    service = make_service(xui_clients=[first_node, second_node])
    client_uuid = "12345678-1234-5678-1234-567812345678"

    with pytest.raises(XuiClientError, match="3x-ui client disable failed"):
        await service.disable_access(client_uuid)

    assert first_node.disable_calls == [client_uuid]
    assert second_node.disable_calls == [client_uuid]
