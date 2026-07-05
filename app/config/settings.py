from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.common.enums import AppEnv


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    dev_mode: bool = False

    app_env: AppEnv = Field(default=AppEnv.DEV, alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")

    database_url: str = Field(alias="DATABASE_URL")

    order_ttl_minutes: int = Field(default=15, alias="ORDER_TTL_MINUTES")
    payment_poll_interval_seconds: int = Field(
        default=15,
        alias="PAYMENT_POLL_INTERVAL_SECONDS",
    )

    volet_sci_enabled: bool = Field(default=False, alias="VOLET_SCI_ENABLED")
    volet_sci_url: str = Field(
        default="https://account.volet.com/sci/",
        alias="VOLET_SCI_URL",
    )
    volet_sci_account_email: str = Field(
        default="",
        alias="VOLET_SCI_ACCOUNT_EMAIL",
    )
    volet_sci_name: str = Field(
        default="",
        alias="VOLET_SCI_NAME",
    )
    volet_sci_password: str = Field(
        default="",
        alias="VOLET_SCI_PASSWORD",
    )
    volet_sci_default_currency: str = Field(
        default="USDT_TRX",
        alias="VOLET_SCI_DEFAULT_CURRENCY",
    )
    volet_sci_success_url: str = Field(
        default="",
        alias="VOLET_SCI_SUCCESS_URL",
    )
    volet_sci_fail_url: str = Field(
        default="",
        alias="VOLET_SCI_FAIL_URL",
    )
    volet_sci_status_url: str = Field(
        default="",
        alias="VOLET_SCI_STATUS_URL",
    )

    volet_sci_payment_base_url: str = Field(
        default="",
        alias="VOLET_SCI_PAYMENT_BASE_URL",
    )
    volet_sci_web_host: str = Field(
        default="0.0.0.0",
        alias="VOLET_SCI_WEB_HOST",
    )
    volet_sci_web_port: int = Field(
        default=2098,
        alias="VOLET_SCI_WEB_PORT",
    )
    

    cryptobot_enabled: bool = Field(default=False, alias="CRYPTOBOT_ENABLED")
    cryptobot_api_url: str = Field(
        default="https://pay.crypt.bot/api",
        alias="CRYPTOBOT_API_URL",
    )
    cryptobot_api_token: str = Field(default="", alias="CRYPTOBOT_API_TOKEN")
    cryptobot_asset: str = Field(default="USDT", alias="CRYPTOBOT_ASSET")
    cryptobot_expires_in: int = Field(default=900, alias="CRYPTOBOT_EXPIRES_IN")

    xray_panel_url: str = Field(default="", alias="XRAY_PANEL_URL")
    xray_panel_username: str = Field(default="", alias="XRAY_PANEL_USERNAME")
    xray_panel_password: str = Field(default="", alias="XRAY_PANEL_PASSWORD")

    xui_base_url: str = Field(default="", alias="XUI_BASE_URL")
    xui_username: str = Field(default="", alias="XUI_USERNAME")
    xui_password: str = Field(default="", alias="XUI_PASSWORD")
    xui_inbound_id: int = Field(default=9, alias="XUI_INBOUND_ID")

    vpn_default_server_name: str = Field(default="default-node", alias="VPN_DEFAULT_SERVER_NAME")
    vpn_default_inbound_id: int = Field(default=1, alias="VPN_DEFAULT_INBOUND_ID")

    support_username: str = Field(default="", alias="SUPPORT_USERNAME")

    subscription_meta_output_path: str = Field(
        default="deploy/vpn-subscription/subscriptions_meta.generated.json",
        alias="SUBSCRIPTION_META_OUTPUT_PATH",
    )
    subscription_meta_remote_target: str = Field(
        default="root@151.243.212.64:/opt/vpn-subscription/subscriptions_meta.json",
        alias="SUBSCRIPTION_META_REMOTE_TARGET",
    )
    subscription_meta_ssh_key: str = Field(
        default="",
        alias="SUBSCRIPTION_META_SSH_KEY",
    )
    subscription_meta_sync_timeout_seconds: int = Field(
        default=60,
        alias="SUBSCRIPTION_META_SYNC_TIMEOUT_SECONDS",
    )


    subscription_expiration_scheduler_enabled: bool = Field(
        default=True,
        alias="SUBSCRIPTION_EXPIRATION_SCHEDULER_ENABLED",
    )
    subscription_expiration_interval_seconds: int = Field(
        default=600,
        alias="SUBSCRIPTION_EXPIRATION_INTERVAL_SECONDS",
    )
    subscription_expiration_initial_delay_seconds: int = Field(
        default=30,
        alias="SUBSCRIPTION_EXPIRATION_INITIAL_DELAY_SECONDS",
    )

    order_expiration_scheduler_enabled: bool = Field(
        default=True,
        alias="ORDER_EXPIRATION_SCHEDULER_ENABLED",
    )
    order_expiration_interval_seconds: int = Field(
        default=600,
        alias="ORDER_EXPIRATION_INTERVAL_SECONDS",
    )
    order_expiration_initial_delay_seconds: int = Field(
        default=45,
        alias="ORDER_EXPIRATION_INITIAL_DELAY_SECONDS",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_value = value.upper()
        if upper_value not in allowed:
            raise ValueError(f"Invalid LOG_LEVEL: {value}")
        return upper_value

    @property
    def admin_ids(self) -> list[int]:
        if not self.admin_ids_raw.strip():
            return []

        result: list[int] = []
        for item in self.admin_ids_raw.split(","):
            item = item.strip()
            if not item:
                continue
            result.append(int(item))
        return result

    @property
    def is_dev(self) -> bool:
        return self.app_env == AppEnv.DEV

    @property
    def is_prod(self) -> bool:
        return self.app_env == AppEnv.PROD


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()