from __future__ import annotations

from datetime import datetime, timezone


def as_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_due_or_past(value: datetime | None, *, now: datetime | None = None) -> bool:
    if value is None:
        return False

    current_time = utc_now() if now is None else now

    return as_utc_aware(value) <= as_utc_aware(current_time)