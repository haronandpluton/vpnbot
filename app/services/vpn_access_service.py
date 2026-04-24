from dataclasses import dataclass
from uuid import uuid4


@dataclass(slots=True)
class VpnAccessResult:
    uuid: str
    vpn_server_id: int | None
    config_uri: str


class VpnAccessService:
    """
    Временный stub вместо реального Xray / 3X-UI.

    Его задача сейчас:
    - сгенерировать UUID;
    - вернуть fake vless:// URI;
    - не ходить во внешний VPN API.
    """

    async def create_access(
        self,
        user_id: int,
        device_limit: int,
    ) -> VpnAccessResult:
        access_uuid = str(uuid4())

        config_uri = (
            f"vless://{access_uuid}@stub-vpn.local:443"
            f"?type=tcp&security=reality"
            f"#vpn-user-{user_id}-{device_limit}-devices"
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
        config_uri = (
            f"vless://{uuid}@stub-vpn.local:443"
            f"?type=tcp&security=reality"
            f"#vpn-renew-{device_limit}-devices"
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
        return (
            f"vless://{uuid}@stub-vpn.local:443"
            f"?type=tcp&security=reality"
            f"#vpn-config-{device_limit}-devices"
        )