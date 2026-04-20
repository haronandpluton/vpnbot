from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.database.enums import subscription_status_enum
from app.payment_core.enums.subscription_status import SubscriptionStatus


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    vpn_server_id: Mapped[int | None] = mapped_column(
        ForeignKey("vpn_servers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        subscription_status_enum,
        nullable=False,
        default=SubscriptionStatus.INACTIVE,
        server_default=SubscriptionStatus.INACTIVE.value,
        index=True,
    )
    uuid: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    device_limit: Mapped[int] = mapped_column(
        nullable=False,
    )

    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    last_access_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    config_version: Mapped[int | None] = mapped_column(
        nullable=True,
    )
    error_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    user = relationship("User", backref="subscriptions")
    order = relationship("Order", backref="subscriptions")
    vpn_server = relationship("VPNServer", backref="subscriptions")

    def __repr__(self) -> str:
        return (
            f"Subscription(id={self.id}, user_id={self.user_id}, "
            f"status={self.status!s}, uuid={self.uuid!r})"
        )