from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.bot.handlers.admin_actions_lookup import _format_actions, _split_text


def make_action(payload: str):
    return SimpleNamespace(
        action_id=1,
        action_type="manual_extend",
        admin_user_id=10,
        admin_telegram_id=123456,
        admin_username="admin_user",
        target_user_id=20,
        order_id=30,
        payment_id=40,
        subscription_id=50,
        reason="<manual reason>",
        payload=payload,
        created_at=datetime(2026, 7, 6, 11, 45, 0),
    )


def test_format_actions_escapes_html_and_truncates_large_payload():
    text = _format_actions(
        "Admin actions — последние 20",
        [
            make_action(
                "<payload>&" + ("x" * 1000),
            ),
        ],
    )

    assert "&lt;payload&gt;&amp;" in text
    assert "&lt;manual reason&gt;" in text
    assert "…" in text
    assert len(text) < 2000


def test_split_text_keeps_chunks_under_limit():
    text = "\n\n".join(
        f"AdminAction #{index}\n" + ("x" * 300)
        for index in range(30)
    )

    chunks = _split_text(text, limit=1000)

    assert len(chunks) > 1
    assert all(len(chunk) <= 1000 for chunk in chunks)