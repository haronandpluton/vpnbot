from dataclasses import dataclass
from uuid import uuid4

from app.config.settings import get_settings
from app.services.xui_client import make_xui_client_from_settings


SUBSCRIPTION_BASE_URL = "https://lab83607.hostkey.in:2097/sub"
CONNECT_BASE_URL = "https://lab83607.hostkey.in:2097/connect"


@dataclass(slots=True)
class VpnAccessResult:
    uuid: str
    vpn_server_id: int | None
    config_uri: str


def build_subscription_url(token: str) -> str:
    return f"{SUBSCRIPTION_BASE_URL}/{token}"


def build_connect_url(token: str, device: str = "android") -> str:
    return f"{CONNECT_BASE_URL}/{token}?device={device}"


def build_client_email(user_id: int, client_uuid: str) -> str:
    return f"tg-{user_id}-{client_uuid[:8]}"


class VpnAccessService:
    """
    Создаёт VPN-доступ в 3x-ui и возвращает пользователю страницу подключения.

    Техническая подписка:
    https://lab83607.hostkey.in:2097/sub/<uuid>

    Пользовательская страница подключения:
    https://lab83607.hostkey.in:2097/connect/<uuid>?device=android
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.xui_client = make_xui_client_from_settings(settings)

    async def create_access(
        self,
        user_id: int,
        device_limit: int,
    ) -> VpnAccessResult:
        access_uuid = str(uuid4())
        email = build_client_email(user_id, access_uuid)

        await self.xui_client.create_vless_client(
            client_uuid=access_uuid,
            email=email,
            device_limit=device_limit,
            comment=f"telegram user {user_id}",
        )

        config_uri = build_connect_url(access_uuid)

        return VpnAccessResult(
            uuid=access_uuid,
            vpn_server_id=None,
            config_uri=config_uri,
        )

    async def extend_access(
        self,
        uuid: str,
        device_limit: int,
    ) -> VpnAccessResult:
        config_uri = build_connect_url(uuid)

        return VpnAccessResult(
            uuid=uuid,
            vpn_server_id=None,
            config_uri=config_uri,
        )

    async def get_config(
        self,
        uuid: str,
        device_limit: int,
    ) -> str:
        return build_connect_url(uuid)