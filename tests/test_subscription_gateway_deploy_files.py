from __future__ import annotations

from pathlib import Path


DEPLOY_DIR = Path("deploy/vpn-subscription")


def test_systemd_unit_runs_dedicated_unprivileged_service_with_hardening():
    text = (DEPLOY_DIR / "vpn-subscription.service").read_text(encoding="utf-8")

    assert "User=vpnsubscription" in text
    assert "Group=vpnsubscription" in text
    assert "EnvironmentFile=/etc/vpn-subscription.env" in text
    assert "ExecStart=/usr/bin/python3 /opt/vpn-subscription/sub_server.py" in text
    assert "NoNewPrivileges=true" in text
    assert "ProtectSystem=strict" in text
    assert "ProtectHome=true" in text
    assert "Restart=on-failure" in text


def test_nginx_terminates_tls_and_proxies_only_to_loopback_http():
    text = (DEPLOY_DIR / "nginx-connect.presentvpn.click.conf").read_text(
        encoding="utf-8"
    )

    assert "server_name connect.presentvpn.click;" in text
    assert "listen 443 ssl;" in text
    assert "proxy_pass http://127.0.0.1:2097;" in text
    assert "proxy_pass https://127.0.0.1:2097;" not in text
    assert "/etc/letsencrypt/live/connect.presentvpn.click/fullchain.pem" in text


def test_gateway_env_example_keeps_public_and_upstream_hosts_separate():
    text = (DEPLOY_DIR / "vpn-subscription.env.example").read_text(
        encoding="utf-8"
    )

    assert (
        "VPN_SUBSCRIPTION_PUBLIC_BASE_URL=https://connect.presentvpn.click" in text
    )
    assert "VPN_UPSTREAM_HOST=lab83607.hostkey.in" in text
    assert "VPN_SUBSCRIPTION_BIND_HOST=127.0.0.1" in text
