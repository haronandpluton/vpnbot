import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import httpx


@dataclass(slots=True)
class XuiConfig:
    base_url: str
    username: str
    password: str
    inbound_id: int


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
        self._validate_uuid(client_uuid)
        expiry_time_ms = self._to_expiry_time_ms(expires_at)
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            csrf = await self._login(client)

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

            response = await client.post(
                f"{self.base_url}/panel/api/clients/add",
                json=payload,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRF-Token": csrf,
                },
            )

            data = self._json(response)

            if not data.get("success"):
                message = data.get("msg") or "unknown 3x-ui client creation error"
                raise XuiClientError(f"3x-ui client creation failed: {message}")

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
            raise XuiClientError(f"3x-ui login failed: {message}")

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
        )
    )