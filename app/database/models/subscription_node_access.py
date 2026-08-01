from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import VPNNodeActualState, VPNNodeDesiredState
from app.database.base import Base, TimestampMixin
from app.database.enums import (
    vpn_node_actual_state_enum,
    vpn_node_desired_state_enum,
)


class SubscriptionNodeAccess(Base, TimestampMixin):
    __tablename__ = "subscription_node_access"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "node_code",
            name="uq_subscription_node_access_subscription_node",
        ),
        Index(
            "ix_subscription_node_access_subscription_states",
            "subscription_id",
            "desired_state",
            "actual_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    desired_state: Mapped[VPNNodeDesiredState] = mapped_column(
        vpn_node_desired_state_enum,
        nullable=False,
        default=VPNNodeDesiredState.ENABLED,
        server_default=VPNNodeDesiredState.ENABLED.value,
        index=True,
    )
    actual_state: Mapped[VPNNodeActualState] = mapped_column(
        vpn_node_actual_state_enum,
        nullable=False,
        default=VPNNodeActualState.PENDING,
        server_default=VPNNodeActualState.PENDING.value,
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    provisioned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    subscription = relationship(
        "Subscription",
        backref="node_accesses",
    )

    def __repr__(self) -> str:
        return (
            "SubscriptionNodeAccess("
            f"id={self.id}, subscription_id={self.subscription_id}, "
            f"node_code={self.node_code!r}, actual_state={self.actual_state!s})"
        )
