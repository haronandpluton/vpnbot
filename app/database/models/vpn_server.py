from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class VPNServer(Base, TimestampMixin):
    __tablename__ = "vpn_servers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
    )
    host: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    panel_url: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    api_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="3xui",
        server_default="3xui",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
    )
    capacity: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    current_load: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"VPNServer(id={self.id}, name={self.name!r}, "
            f"status={self.status!r})"
        )