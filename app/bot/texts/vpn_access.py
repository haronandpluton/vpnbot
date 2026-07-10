def format_datetime(value) -> str:
    if value is None:
        return "not specified"

    return value.strftime("%d.%m.%Y %H:%M")


def format_vpn_access_text(
    *,
    device_limit: int | None,
    expires_at,
) -> str:
    expires_at_text = format_datetime(expires_at)

    return (
        "Your VPN subscription is active.\n\n"
        f"Devices: {device_limit or '—'}\n"
        f"Active until: {expires_at_text}\n\n"
        "Use Happ VPN to connect.\n\n"
        "Click “Connect VPN”, then open the connection page. "
        "Happ VPN should open automatically and import the subscription."
    )



def format_expired_vpn_subscription_text(
    *,
    device_limit: int | None,
    expires_at,
) -> str:
    expires_at_text = format_datetime(expires_at)

    return (
        "Your VPN subscription has expired.\n\n"
        f"Devices: {device_limit or '—'}\n"
        f"Was active until: {expires_at_text}\n\n"
        "Click “Renew Subscription” to restore access "
        "with the same VPN key."
    )


def format_vpn_config_text(config_uri: str) -> str:
    return (
        "VPN connection page:\n\n"
        "Click the button below to open the connection page. Happ VPN "
        "should then open automatically and import the subscription.\n\n"
        "If automatic opening does not work, the page will have an "
        "“Open Manually” button and a backup “Copy” button.\n\n"
        "Backup link:\n"
        f"<code>{config_uri}</code>"
    )


def happ_android_instruction_text() -> str:
    return (
        "Connecting through Happ VPN on Android:\n\n"
        "1. Install Happ VPN.\n"
        "2. Click “Connect VPN” in this bot.\n"
        "3. Click “Open in Happ VPN”.\n"
        "4. Confirm opening the app if Android asks for permission.\n"
        "5. Happ VPN will import the subscription.\n"
        "6. Select the added profile and enable the VPN."
    )


def happ_ios_instruction_text() -> str:
    return (
        "Connecting on iPhone:\n\n"
        "1. Install Happ VPN or another client that supports VLESS subscriptions.\n"
        "2. Click “Connect VPN” in this bot.\n"
        "3. Open the connection page.\n"
        "4. If automatic import does not work, copy the link from the page "
        "and add it in the app as a Subscription / URL."
    )


def happ_fallback_text() -> str:
    return (
        "If Happ VPN did not open automatically:\n\n"
        "1. Click “Connect VPN”.\n"
        "2. On the connection page, click “Open Manually”.\n"
        "3. If that does not work, click “Copy”.\n"
        "4. Open Happ VPN manually.\n"
        "5. Click + and select “Import/Paste from Clipboard” or Subscription / URL.\n\n"
        "The supported connection format is already prepared automatically on the page."
    )
