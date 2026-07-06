from __future__ import annotations

from datetime import datetime, timezone

from app.common.datetime_utils import as_utc_aware, is_due_or_past


def test_as_utc_aware_treats_naive_datetime_as_utc():
    value = datetime(2026, 7, 6, 8, 0)

    result = as_utc_aware(value)

    assert result.tzinfo is not None
    assert result.isoformat() == "2026-07-06T08:00:00+00:00"


def test_as_utc_aware_keeps_aware_utc_datetime():
    value = datetime(2026, 7, 6, 8, 0, tzinfo=timezone.utc)

    result = as_utc_aware(value)

    assert result == value


def test_is_due_or_past_accepts_naive_expiry_and_aware_now():
    expires_at = datetime(2026, 7, 6, 8, 0)
    now = datetime(2026, 7, 6, 8, 1, tzinfo=timezone.utc)

    assert is_due_or_past(expires_at, now=now) is True


def test_is_due_or_past_returns_false_for_future_naive_expiry():
    expires_at = datetime(2026, 7, 6, 8, 2)
    now = datetime(2026, 7, 6, 8, 1, tzinfo=timezone.utc)

    assert is_due_or_past(expires_at, now=now) is False


def test_is_due_or_past_returns_false_for_none():
    now = datetime(2026, 7, 6, 8, 1, tzinfo=timezone.utc)

    assert is_due_or_past(None, now=now) is False