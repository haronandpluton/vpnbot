from dataclasses import dataclass
from urllib.parse import quote, urlencode
from uuid import uuid4

from app.config.settings import get_settings
from app.services.xui_client import make_xui_client_from_settings


DEFAULT_PUBLIC_BASE_URL = "https://connect.presentvpn.click"


@dataclass(slots=True)
class VpnAccessResult:
    uuid: str
    vpn_server_id: int | None
    config_uri: str


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


class VpnAccessService:
    """
    Создаёт VPN-доступ на EU VPN-ноде через 3x-ui и возвращает
    пользовательскую страницу подключения на отдельном ZA gateway.

    Основная подписка:
    https://connect.presentvpn.click/<uuid>

    Пользовательская страница подключения:
    https://connect.presentvpn.click/connect/<uuid>?device=android
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.xui_client = make_xui_client_from_settings(settings)
        self.public_base_url = settings.vpn_subscription_public_base_url

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
    ) -> VpnAccessResult:
        config_uri = build_connect_url(
            uuid,
            public_base_url=self.public_base_url,
        )

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
        return build_connect_url(
            uuid,
            public_base_url=self.public_base_url,
        )
