from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True,
    )
    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    first_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    last_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    language_code: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    is_blocked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    def __repr__(self) -> str:
        return (
            f"User(id={self.id}, telegram_id={self.telegram_id}, "
            f"username={self.username!r})"
        )