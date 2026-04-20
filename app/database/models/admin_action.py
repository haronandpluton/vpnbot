from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class AdminAction(Base, TimestampMixin):
    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    admin_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    action_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    payload: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    admin_user = relationship(
        "User",
        foreign_keys=[admin_user_id],
        backref="performed_admin_actions",
    )
    target_user = relationship(
        "User",
        foreign_keys=[target_user_id],
        backref="received_admin_actions",
    )
    order = relationship("Order", backref="admin_actions")
    payment = relationship("Payment", backref="admin_actions")
    subscription = relationship("Subscription", backref="admin_actions")

    def __repr__(self) -> str:
        return (
            f"AdminAction(id={self.id}, action_type={self.action_type!r}, "
            f"admin_user_id={self.admin_user_id})"
        )