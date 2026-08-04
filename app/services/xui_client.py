import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote
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

        Exact retries are no-ops. When the same UUID/email already exists with
        an older expiry or device limit, the existing record is reconciled
        instead of creating a duplicate. Conflicting UUID/email identities are
        still rejected.
        """
        self._validate_uuid(client_uuid)
        expiry_time_ms = self._to_expiry_time_ms(expires_at)

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            csrf = await self._login(client)
            existing = await self._get_client_by_identity(
                client,
                client_uuid=client_uuid,
                email=email,
            )

            if existing is not None:
                if self._client_matches_desired_state(
                    existing,
                    device_limit=device_limit,
                    expiry_time_ms=expiry_time_ms,
                ):
                    return

                await self._update_existing_client(
                    client,
                    csrf=csrf,
                    existing=existing,
                    client_uuid=client_uuid,
                    device_limit=device_limit,
                    expiry_time_ms=expiry_time_ms,
                )
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
                    headers=self._api_headers(csrf),
                )
                data = self._json(response)
            except (httpx.HTTPError, XuiClientError) as error:
                if await self._client_has_desired_state(
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
            if await self._client_has_desired_state(
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

    async def update_vless_client(
        self,
        *,
        client_uuid: str,
        device_limit: int,
        expires_at: datetime,
    ) -> None:
        """Synchronize expiry/device limit for an existing VLESS client."""
        self._validate_uuid(client_uuid)
        expiry_time_ms = self._to_expiry_time_ms(expires_at)

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            csrf = await self._login(client)
            existing = await self._get_client_by_uuid(client, client_uuid)

            if existing is None:
                raise XuiClientError(
                    "3x-ui client not found on "
                    f"{self.config.name}: uuid={client_uuid}"
                )

            if self._client_matches_desired_state(
                existing,
                device_limit=device_limit,
                expiry_time_ms=expiry_time_ms,
            ):
                return

            await self._update_existing_client(
                client,
                csrf=csrf,
                existing=existing,
                client_uuid=client_uuid,
                device_limit=device_limit,
                expiry_time_ms=expiry_time_ms,
            )

    async def enable_vless_client(self, *, client_uuid: str) -> None:
        """Idempotently enable an existing VLESS client."""
        await self._set_vless_client_enabled(
            client_uuid=client_uuid,
            enabled=True,
        )

    async def disable_vless_client(self, *, client_uuid: str) -> None:
        """Idempotently disable an existing VLESS client."""
        await self._set_vless_client_enabled(
            client_uuid=client_uuid,
            enabled=False,
        )

    async def _set_vless_client_enabled(
        self,
        *,
        client_uuid: str,
        enabled: bool,
    ) -> None:
        self._validate_uuid(client_uuid)
        desired_enabled = bool(enabled)

        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
        ) as client:
            csrf = await self._login(client)
            existing = await self._get_client_by_uuid(
                client,
                client_uuid,
            )

            if existing is None:
                # Absence is already the terminal disabled state.
                # Enabling an absent client remains an error.
                if not desired_enabled:
                    return

                raise XuiClientError(
                    "3x-ui client not found on "
                    f"{self.config.name}: uuid={client_uuid}"
                )

            if (
                bool(existing.get("enable", True))
                == desired_enabled
            ):
                return

            email = str(
                existing.get("email") or ""
            ).strip()

            if not email:
                raise XuiClientError(
                    "3x-ui client has no email on "
                    f"{self.config.name}: uuid={client_uuid}"
                )

            try:
                data = await self._replace_client(
                    client,
                    csrf=csrf,
                    email=email,
                    client_uuid=client_uuid,
                    changes={
                        "enable": desired_enabled,
                    },
                )
            except (
                httpx.HTTPError,
                XuiClientError,
            ) as error:
                if await self._client_has_enabled_state(
                    client,
                    client_uuid=client_uuid,
                    enabled=desired_enabled,
                ):
                    return

                raise error

            if not data.get("success"):
                if await self._client_has_enabled_state(
                    client,
                    client_uuid=client_uuid,
                    enabled=desired_enabled,
                ):
                    return

                message = (
                    data.get("msg")
                    or "unknown 3x-ui client state update error"
                )

                raise XuiClientError(
                    "3x-ui client state update failed on "
                    f"{self.config.name}: {message}"
                )

            if not await self._client_has_enabled_state(
                client,
                client_uuid=client_uuid,
                enabled=desired_enabled,
            ):
                raise XuiClientError(
                    "3x-ui client state update was not applied on "
                    f"{self.config.name}: "
                    f"uuid={client_uuid} "
                    f"enabled={desired_enabled}"
                )

    async def _update_existing_client(
        self,
        client: httpx.AsyncClient,
        *,
        csrf: str,
        existing: dict[str, Any],
        client_uuid: str,
        device_limit: int,
        expiry_time_ms: int,
    ) -> None:
        email = str(
            existing.get("email") or ""
        ).strip()

        if not email:
            raise XuiClientError(
                "3x-ui client has no email on "
                f"{self.config.name}: uuid={client_uuid}"
            )

        try:
            data = await self._replace_client(
                client,
                csrf=csrf,
                email=email,
                client_uuid=client_uuid,
                changes={
                    "limitIp": int(device_limit or 0),
                    "expiryTime": expiry_time_ms,
                    "enable": True,
                },
            )
        except (
            httpx.HTTPError,
            XuiClientError,
        ) as error:
            if await self._client_has_desired_state(
                client,
                client_uuid=client_uuid,
                email=email,
                device_limit=device_limit,
                expiry_time_ms=expiry_time_ms,
            ):
                return

            raise error

        if not data.get("success"):
            if await self._client_has_desired_state(
                client,
                client_uuid=client_uuid,
                email=email,
                device_limit=device_limit,
                expiry_time_ms=expiry_time_ms,
            ):
                return

            message = (
                data.get("msg")
                or "unknown 3x-ui client update error"
            )

            raise XuiClientError(
                "3x-ui client update failed on "
                f"{self.config.name}: {message}"
            )

        if not await self._client_has_desired_state(
            client,
            client_uuid=client_uuid,
            email=email,
            device_limit=device_limit,
            expiry_time_ms=expiry_time_ms,
        ):
            raise XuiClientError(
                "3x-ui client update was not applied on "
                f"{self.config.name}: uuid={client_uuid}"
            )

    async def _replace_client(
        self,
        client: httpx.AsyncClient,
        *,
        csrf: str,
        email: str,
        client_uuid: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        full_client = await self._get_full_client_by_email(
            client,
            csrf=csrf,
            email=email,
        )

        actual_uuid = str(
            full_client.get("uuid") or ""
        )

        if actual_uuid != client_uuid:
            raise XuiClientError(
                "3x-ui UUID conflict on "
                f"{self.config.name}: "
                f"email={email} "
                f"expected_uuid={client_uuid} "
                f"existing_uuid={actual_uuid}"
            )

        # /clients/get returns a read DTO:
        #   id = numeric database row ID
        #   uuid = VLESS UUID
        #
        # /clients/update accepts a write DTO:
        #   id = VLESS UUID string
        updated = dict(full_client)

        updated.pop("uuid", None)
        updated.pop("createdAt", None)
        updated.pop("updatedAt", None)
        updated.pop("traffic", None)
        updated.pop("inboundIds", None)

        updated["id"] = client_uuid
        updated.update(changes)

        encoded_email = quote(
            email,
            safe="",
        )

        response = await client.post(
            (
                f"{self.base_url}"
                f"/panel/api/clients/update/"
                f"{encoded_email}"
            ),
            json=updated,
            headers=self._api_headers(csrf),
        )

        return self._json(response)

    async def _get_full_client_by_email(
        self,
        client: httpx.AsyncClient,
        *,
        csrf: str,
        email: str,
    ) -> dict[str, Any]:
        encoded_email = quote(
            email,
            safe="",
        )

        response = await client.get(
            (
                f"{self.base_url}"
                f"/panel/api/clients/get/"
                f"{encoded_email}"
            ),
            headers=self._api_headers(csrf),
        )

        data = self._json(response)

        if not data.get("success"):
            message = (
                data.get("msg")
                or "unknown 3x-ui client lookup error"
            )

            raise XuiClientError(
                "3x-ui client lookup failed on "
                f"{self.config.name}: {message}"
            )

        obj = data.get("obj")

        if not isinstance(obj, dict):
            raise XuiClientError(
                "3x-ui returned invalid client object on "
                f"{self.config.name}"
            )

        full_client = obj.get("client")

        if not isinstance(full_client, dict):
            raise XuiClientError(
                "3x-ui returned invalid client record on "
                f"{self.config.name}"
            )

        actual_email = str(
            full_client.get("email") or ""
        )

        if actual_email != email:
            raise XuiClientError(
                "3x-ui returned unexpected client identity on "
                f"{self.config.name}: "
                f"expected_email={email} "
                f"actual_email={actual_email}"
            )

        return dict(full_client)

    async def _get_client_by_identity(
        self,
        client: httpx.AsyncClient,
        *,
        client_uuid: str,
        email: str,
    ) -> dict[str, Any] | None:
        clients = await self._get_inbound_clients(client)
        by_email = [item for item in clients if item.get("email") == email]
        by_uuid = [item for item in clients if item.get("id") == client_uuid]
        exact = [
            item
            for item in clients
            if item.get("email") == email and item.get("id") == client_uuid
        ]

        if len(exact) > 1:
            raise XuiClientError(
                "3x-ui contains duplicate client records on "
                f"{self.config.name}: email={email} uuid={client_uuid}"
            )

        if exact:
            return exact[0]

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

        return None

    async def _get_client_by_uuid(
        self,
        client: httpx.AsyncClient,
        client_uuid: str,
    ) -> dict[str, Any] | None:
        clients = await self._get_inbound_clients(client)
        matches = [item for item in clients if item.get("id") == client_uuid]

        if len(matches) > 1:
            raise XuiClientError(
                "3x-ui contains duplicate client UUID records on "
                f"{self.config.name}: uuid={client_uuid}"
            )

        return matches[0] if matches else None

    async def _client_has_desired_state(
        self,
        client: httpx.AsyncClient,
        *,
        client_uuid: str,
        email: str,
        device_limit: int,
        expiry_time_ms: int,
    ) -> bool:
        existing = await self._get_client_by_identity(
            client,
            client_uuid=client_uuid,
            email=email,
        )
        return existing is not None and self._client_matches_desired_state(
            existing,
            device_limit=device_limit,
            expiry_time_ms=expiry_time_ms,
        )

    async def _client_has_enabled_state(
        self,
        client: httpx.AsyncClient,
        *,
        client_uuid: str,
        enabled: bool,
    ) -> bool:
        existing = await self._get_client_by_uuid(client, client_uuid)
        return (
            existing is not None
            and bool(existing.get("enable", True)) == bool(enabled)
        )

    @staticmethod
    def _client_matches_desired_state(
        existing: dict[str, Any],
        *,
        device_limit: int,
        expiry_time_ms: int,
    ) -> bool:
        return (
            int(existing.get("limitIp") or 0) == int(device_limit or 0)
            and int(existing.get("expiryTime") or 0) == expiry_time_ms
            and bool(existing.get("enable", True))
        )

    @staticmethod
    def _api_headers(csrf: str) -> dict[str, str]:
        return {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf,
        }

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
