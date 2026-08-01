import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx


@dataclass(slots=True)
class XuiConfig:
    base_url: str
    username: str
    password: str
    inbound_id: int
    name: str = "default"


class XuiClientError(RuntimeError):
    pass


class XuiClient:
    def __init__(self, config: XuiConfig) -> None:
        self.config = config
        self.base_url = config.base_url.rstrip("/")

    async def create_vless_client(
        self,
        *,
        client_uuid: str,
        email: str,
        device_limit: int,
        expires_at: datetime | None = None,
        comment: str = "",
    ) -> None:
        """
        Idempotently ensure that the requested VLESS client exists.

        A repeated activation with the same email/UUID and limits is a no-op.
        Conflicting email/UUID records are rejected instead of being silently
        overwritten. This makes partial multi-node retries safe.
        """
        self._validate_uuid(client_uuid)
        expiry_time_ms = self._to_expiry_time_ms(expires_at)

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            csrf = await self._login(client)

            if await self._client_exists_exactly(
                client,
                client_uuid=client_uuid,
                email=email,
                device_limit=device_limit,
                expiry_time_ms=expiry_time_ms,
            ):
                return

            payload = {
                "client": {
                    "email": email,
                    "subId": secrets.token_hex(8),
                    "id": client_uuid,
                    "password": "",
                    "auth": "",
                    "flow": "",
                    "security": "auto",
                    "totalGB": 0,
                    "expiryTime": expiry_time_ms,
                    "limitIp": int(device_limit or 0),
                    "tgId": 0,
                    "reset": 0,
                    "group": "",
                    "comment": comment,
                    "enable": True,
                },
                "inboundIds": [self.config.inbound_id],
            }

            try:
                response = await client.post(
                    f"{self.base_url}/panel/api/clients/add",
                    json=payload,
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRF-Token": csrf,
                    },
                )
                data = self._json(response)
            except (httpx.HTTPError, XuiClientError) as error:
                if await self._client_exists_exactly(
                    client,
                    client_uuid=client_uuid,
                    email=email,
                    device_limit=device_limit,
                    expiry_time_ms=expiry_time_ms,
                ):
                    return
                raise error

            if data.get("success"):
                return

            # A concurrent/retried request may have created the client after the
            # initial lookup. Re-read before treating a duplicate response as an
            # error.
            if await self._client_exists_exactly(
                client,
                client_uuid=client_uuid,
                email=email,
                device_limit=device_limit,
                expiry_time_ms=expiry_time_ms,
            ):
                return

            message = data.get("msg") or "unknown 3x-ui client creation error"
            raise XuiClientError(
                f"3x-ui client creation failed on {self.config.name}: {message}"
            )

    async def _client_exists_exactly(
        self,
        client: httpx.AsyncClient,
        *,
        client_uuid: str,
        email: str,
        device_limit: int,
        expiry_time_ms: int,
    ) -> bool:
        clients = await self._get_inbound_clients(client)

        by_email = [item for item in clients if item.get("email") == email]
        by_uuid = [item for item in clients if item.get("id") == client_uuid]

        exact = [
            item
            for item in clients
            if item.get("email") == email and item.get("id") == client_uuid
        ]

        if exact:
            if len(exact) > 1:
                raise XuiClientError(
                    "3x-ui contains duplicate client records on "
                    f"{self.config.name}: email={email} uuid={client_uuid}"
                )

            existing = exact[0]
            existing_limit = int(existing.get("limitIp") or 0)
            existing_expiry = int(existing.get("expiryTime") or 0)
            existing_enabled = bool(existing.get("enable", True))

            if (
                existing_limit != int(device_limit or 0)
                or existing_expiry != expiry_time_ms
                or not existing_enabled
            ):
                raise XuiClientError(
                    "3x-ui client already exists with different parameters on "
                    f"{self.config.name}: email={email} uuid={client_uuid}"
                )

            return True

        if by_email:
            existing_uuid = by_email[0].get("id")
            raise XuiClientError(
                "3x-ui email conflict on "
                f"{self.config.name}: email={email} existing_uuid={existing_uuid}"
            )

        if by_uuid:
            existing_email = by_uuid[0].get("email")
            raise XuiClientError(
                "3x-ui UUID conflict on "
                f"{self.config.name}: uuid={client_uuid} existing_email={existing_email}"
            )

        return False

    async def _get_inbound_clients(
        self,
        client: httpx.AsyncClient,
    ) -> list[dict[str, Any]]:
        response = await client.get(
            f"{self.base_url}/panel/api/inbounds/get/{self.config.inbound_id}"
        )
        response.raise_for_status()
        data = self._json(response)

        if not data.get("success"):
            message = data.get("msg") or "unknown 3x-ui inbound lookup error"
            raise XuiClientError(
                f"3x-ui inbound lookup failed on {self.config.name}: {message}"
            )

        obj = data.get("obj")
        if not isinstance(obj, dict):
            raise XuiClientError(
                f"3x-ui returned invalid inbound on {self.config.name}"
            )

        settings = obj.get("settings")
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except json.JSONDecodeError as error:
                raise XuiClientError(
                    "3x-ui returned invalid inbound settings on "
                    f"{self.config.name}"
                ) from error

        if not isinstance(settings, dict):
            raise XuiClientError(
                f"3x-ui returned invalid inbound settings on {self.config.name}"
            )

        clients = settings.get("clients", [])
        if not isinstance(clients, list) or not all(
            isinstance(item, dict) for item in clients
        ):
            raise XuiClientError(
                f"3x-ui returned invalid client list on {self.config.name}"
            )

        return clients

    async def _login(self, client: httpx.AsyncClient) -> str:
        page_response = await client.get(f"{self.base_url}/")
        page_response.raise_for_status()

        csrf = self._extract_csrf(page_response.text)

        login_response = await client.post(
            f"{self.base_url}/login",
            data={
                "username": self.config.username,
                "password": self.config.password,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-Token": csrf,
            },
        )

        data = self._json(login_response)

        if not data.get("success"):
            message = data.get("msg") or "unknown 3x-ui login error"
            raise XuiClientError(
                f"3x-ui login failed on {self.config.name}: {message}"
            )

        panel_response = await client.get(f"{self.base_url}/panel/")
        panel_response.raise_for_status()

        panel_csrf = self._extract_csrf(panel_response.text)
        return panel_csrf

    @staticmethod
    def _extract_csrf(html: str) -> str:
        match = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
        if not match:
            raise XuiClientError("CSRF token not found in 3x-ui page")

        return match.group(1)

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            data = response.json()
        except ValueError as error:
            raise XuiClientError(
                f"3x-ui returned non-json response: HTTP {response.status_code}"
            ) from error

        if not isinstance(data, dict):
            raise XuiClientError("3x-ui returned invalid json structure")

        return data

    @staticmethod
    def _to_expiry_time_ms(value: datetime | None) -> int:
        if value is None:
            return 0

        if value.tzinfo is None or value.utcoffset() is None:
            raise XuiClientError("expires_at must be timezone-aware")

        return int(value.timestamp() * 1000)

    @staticmethod
    def _validate_uuid(value: str) -> None:
        try:
            UUID(value)
        except ValueError as error:
            raise XuiClientError(f"invalid client uuid: {value}") from error


def make_xui_client_from_settings(settings) -> XuiClient:
    return XuiClient(
        XuiConfig(
            base_url=settings.xui_base_url,
            username=settings.xui_username,
            password=settings.xui_password,
            inbound_id=settings.xui_inbound_id,
            name="legacy-default",
        )
    )


def make_xui_clients_from_settings(settings) -> list[XuiClient]:
    raw_nodes = str(getattr(settings, "vpn_xui_nodes_json", "") or "").strip()
    if not raw_nodes:
        return [make_xui_client_from_settings(settings)]

    try:
        parsed = json.loads(raw_nodes)
    except json.JSONDecodeError as error:
        raise XuiClientError("VPN_XUI_NODES_JSON must contain valid JSON") from error

    if not isinstance(parsed, list):
        raise XuiClientError("VPN_XUI_NODES_JSON must be a JSON list")

    result: list[XuiClient] = []
    names: set[str] = set()

    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise XuiClientError(
                f"VPN_XUI_NODES_JSON item {index} must be an object"
            )

        if not bool(item.get("enabled", True)):
            continue

        name = str(item.get("name") or f"node-{index + 1}").strip()
        base_url = str(item.get("base_url") or "").strip()
        username = str(item.get("username") or "").strip()
        password = str(item.get("password") or "")

        try:
            inbound_id = int(item.get("inbound_id"))
        except (TypeError, ValueError) as error:
            raise XuiClientError(
                f"VPN_XUI_NODES_JSON node {name!r} has invalid inbound_id"
            ) from error

        if not name or not base_url or not username or not password or inbound_id <= 0:
            raise XuiClientError(
                f"VPN_XUI_NODES_JSON node {name!r} is incomplete"
            )

        if name in names:
            raise XuiClientError(
                f"VPN_XUI_NODES_JSON contains duplicate node name: {name}"
            )
        names.add(name)

        result.append(
            XuiClient(
                XuiConfig(
                    name=name,
                    base_url=base_url,
                    username=username,
                    password=password,
                    inbound_id=inbound_id,
                )
            )
        )

    if not result:
        raise XuiClientError("VPN_XUI_NODES_JSON has no enabled nodes")

    return result
