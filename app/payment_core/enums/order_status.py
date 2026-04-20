from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    CREATED = "created"
    WAITING_PAYMENT = "waiting_payment"
    PAID = "paid"
    ACTIVATED = "activated"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"