from __future__ import annotations

from enum import StrEnum


class PaymentStatus(StrEnum):
    NEW = "new"
    DETECTED = "detected"
    CONFIRMED = "confirmed"
    INVALID = "invalid"
    DUPLICATE = "duplicate"
    EXPIRED = "expired"
    ERROR = "error"