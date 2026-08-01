import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlencode
from uuid import UUID, uuid4

from app.config.settings import get_settings
from app.services.xui_client import (
    XuiClient,
    make_xui_clients_from_settings,
)

DEFAULT_PUBLIC_BASE_URL = "https://connect.presentvpn.click"


@dataclass(slots=True)
class VpnAccessResult:
    uuid: str
    vpn_server_id: int | None
    config_uri: str


@dataclass(frozen=True, slots=True)
class VpnNodeFailure:
    node_name: str
    error: str


class VpnNodeOperationError(RuntimeError):
    def __init__(
        self,
        *,
        operation: str,
        uuid: str,
        failures: list[VpnNodeFailure],
    ) -> None:
        self.operation = operation
        self.uuid = uuid
        self.failures = tuple(failures)
        details = "; ".join(
            f"{failure.node_name}: {failure.error}" for failure in self.failures
        )
        super().__init__(
            f"VPN {operation} failed on {len(self.failures)} node(s) "
            f"for uuid={uuid}: {details}"
        )


def _normalize_public_base_url(public_base_url: str) -> str:
    return public_base_url.rstrip("/")


def build_subscription_url(
    token: str,
    *,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
) -> str:
    base_url = _normalize_public_base_url(public_base_url)
    return f"{base_url}/{quote(token, safe='')}"


def build_connect_url(
    token: str,
    device: str = "android",
    *,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
) -> str:
    base_url = _normalize_public_base_url(public_base_url)
    query = urlencode({"device": device})
    return f"{base_url}/connect/{quote(token, safe='')}?{query}"


def build_client_email(user_id: int, client_uuid: str) -> str:
    return f"tg-{user_id}-{client_uuid[:8]}"


def build_idempotent_uuid(*, secret: str, idempotency_key: str) -> str:
    """
    Build an unguessable, stable UUID for one activation operation.

    HMAC makes the UUID deterministic for retries while keeping it impossible
    to derive from an order/user identifier without the server-side secret.
    """
    if not secret:
        raise ValueError("VPN access UUID secret must not be empty")
    if not idempotency_key:
        raise ValueError("VPN access idempotency key must not be empty")

    digest = bytearray(
        hmac.new(
            secret.encode("utf-8"),
            idempotency_key.encode("utf-8"),
            hashlib.sha256,
        ).digest()[:16]
    )
    # Mark the result as RFC 4122 variant and version 4. The bytes are still
    # deterministic because they come from HMAC rather than random input.
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(digest)))


class VpnAccessService:
    """
    Creates the same VPN credential on every configured 3X-UI node and returns
    the public subscription setup page hosted by the regional gateway.

    When VPN_XUI_NODES_JSON is empty, the legacy single XUI_* configuration is
    used. This keeps existing deployments backward-compatible.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.xui_clients = make_xui_clients_from_settings(settings)
        # Compatibility with tests/older integration code that accesses the
        # former single-client attribute directly.
        self.xui_client = self.xui_clients[0]
        self.public_base_url = settings.vpn_subscription_public_base_url
        self.uuid_secret = (
            settings.vpn_access_uuid_secret.strip() or settings.bot_token
        )

    def _configured_xui_clients(self) -> list[XuiClient]:
        clients = getattr(self, "xui_clients", None)
        if clients is not None:
            return list(clients)

        # Compatibility for services constructed with __new__ in unit tests and
        # for old custom wiring that only assigns xui_client.
        return [self.xui_client]

    def configured_node_names(self) -> tuple[str, ...]:
        """Return stable node codes used by per-subscription state tracking."""
        result: list[str] = []
        seen: set[str] = set()

        for index, xui_client in enumerate(self._configured_xui_clients(), start=1):
            config = getattr(xui_client, "config", None)
            node_name = str(
                getattr(config, "name", "") or f"node-{index}"
            ).strip()

            if not node_name:
                raise ValueError("Configured VPN node name must not be empty")
            if node_name in seen:
                raise ValueError(
                    f"Duplicate configured VPN node name: {node_name}"
                )

            seen.add(node_name)
            result.append(node_name)

        if not result:
            raise ValueError("At least one VPN node must be configured")

        return tuple(result)

    async def create_access(
        self,
        user_id: int,
        device_limit: int,
        expires_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> VpnAccessResult:
        if idempotency_key is None:
            access_uuid = str(uuid4())
        else:
            access_uuid = build_idempotent_uuid(
                secret=self.uuid_secret,
                idempotency_key=idempotency_key,
            )

        email = build_client_email(user_id, access_uuid)

        for xui_client in self._configured_xui_clients():
            await xui_client.create_vless_client(
                client_uuid=access_uuid,
                email=email,
                device_limit=device_limit,
                expires_at=expires_at,
                comment=f"telegram user {user_id}",
            )

        config_uri = build_connect_url(
            access_uuid,
            public_base_url=self.public_base_url,
        )

        return VpnAccessResult(
            uuid=access_uuid,
            vpn_server_id=None,
            config_uri=config_uri,
        )

    async def extend_access(
        self,
        uuid: str,
        device_limit: int,
        expires_at: datetime,
    ) -> VpnAccessResult:
        for xui_client in self._configured_xui_clients():
            await xui_client.update_vless_client(
                client_uuid=uuid,
                device_limit=device_limit,
                expires_at=expires_at,
            )

        config_uri = build_connect_url(
            uuid,
            public_base_url=self.public_base_url,
        )

        return VpnAccessResult(
            uuid=uuid,
            vpn_server_id=None,
            config_uri=config_uri,
        )

    async def enable_access(self, uuid: str) -> VpnAccessResult:
        for xui_client in self._configured_xui_clients():
            await xui_client.enable_vless_client(client_uuid=uuid)

        return self._access_result(uuid)

    async def disable_access(self, uuid: str) -> VpnAccessResult:
        failures: list[VpnNodeFailure] = []

        for index, xui_client in enumerate(self._configured_xui_clients(), start=1):
            try:
                await xui_client.disable_vless_client(client_uuid=uuid)
            except Exception as error:  # noqa: BLE001 - isolate node failures
                config = getattr(xui_client, "config", None)
                node_name = str(getattr(config, "name", "") or f"node-{index}")
                failures.append(
                    VpnNodeFailure(
                        node_name=node_name,
                        error=str(error),
                    )
                )

        if failures:
            raise VpnNodeOperationError(
                operation="disable",
                uuid=uuid,
                failures=failures,
            )

        return self._access_result(uuid)

    def _access_result(self, uuid: str) -> VpnAccessResult:
        return VpnAccessResult(
            uuid=uuid,
            vpn_server_id=None,
            config_uri=build_connect_url(
                uuid,
                public_base_url=self.public_base_url,
            ),
        )

    async def get_config(
        self,
        uuid: str,
        device_limit: int,
    ) -> str:
        return build_connect_url(
            uuid,
            public_base_url=self.public_base_url,
        )
