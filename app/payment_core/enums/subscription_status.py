from enum import StrEnum


class SubscriptionStatus(StrEnum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    EXPIRED = "expired"
    DISABLED = "disabled"
    ERROR = "error"