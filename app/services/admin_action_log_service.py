from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AdminAction, User


@dataclass
class AdminActionLogResult:
    status: str
    action_id: int | None = None
    admin_user_id: int | None = None
    message: str | None = None


class AdminActionLogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_action_by_admin_telegram_id(
        self,
        admin_telegram_id: int,
        action_type: str,
        target_user_id: int | None = None,
        order_id: int | None = None,
        payment_id: int | None = None,
        subscription_id: int | None = None,
        reason: str | None = None,
        payload: str | None = None,
        commit: bool = True,
    ) -> AdminActionLogResult:
        admin_user = await self._get_user_by_telegram_id(admin_telegram_id)

        if admin_user is None:
            return AdminActionLogResult(
                status="admin_user_not_found",
                message="Admin user not found in users table.",
            )

        action = AdminAction(
            admin_user_id=admin_user.id,
            target_user_id=target_user_id,
            order_id=order_id,
            payment_id=payment_id,
            subscription_id=subscription_id,
            action_type=action_type,
            reason=reason,
            payload=payload,
        )

        self.session.add(action)

        if commit:
            await self.session.commit()
            await self.session.refresh(action)
        else:
            await self.session.flush()

        return AdminActionLogResult(
            status="created",
            action_id=action.id,
            admin_user_id=admin_user.id,
            message="Admin action logged.",
        )

    async def _get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


@dataclass
class AdminActionListItem:
    action_id: int
    admin_user_id: int
    admin_telegram_id: int | None
    admin_username: str | None
    target_user_id: int | None
    action_type: str
    reason: str | None
    order_id: int | None
    payment_id: int | None
    subscription_id: int | None
    payload: str | None
    created_at: datetime | None


class AdminActionLookupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_last_actions(self, limit: int = 20) -> list[AdminActionListItem]:
        result = await self.session.execute(
            select(AdminAction, User)
            .join(User, AdminAction.admin_user_id == User.id)
            .order_by(AdminAction.created_at.desc())
            .limit(limit)
        )

        return [
            self._build_item(action=action, admin_user=admin_user)
            for action, admin_user in result.all()
        ]

    async def get_actions_by_subscription_id(
        self,
        subscription_id: int,
        limit: int = 20,
    ) -> list[AdminActionListItem]:
        result = await self.session.execute(
            select(AdminAction, User)
            .join(User, AdminAction.admin_user_id == User.id)
            .where(AdminAction.subscription_id == subscription_id)
            .order_by(AdminAction.created_at.desc())
            .limit(limit)
        )

        return [
            self._build_item(action=action, admin_user=admin_user)
            for action, admin_user in result.all()
        ]

    async def get_actions_by_target_user_id(
        self,
        target_user_id: int,
        limit: int = 20,
    ) -> list[AdminActionListItem]:
        result = await self.session.execute(
            select(AdminAction, User)
            .join(User, AdminAction.admin_user_id == User.id)
            .where(AdminAction.target_user_id == target_user_id)
            .order_by(AdminAction.created_at.desc())
            .limit(limit)
        )

        return [
            self._build_item(action=action, admin_user=admin_user)
            for action, admin_user in result.all()
        ]

    @staticmethod
    def _build_item(
        action: AdminAction,
        admin_user: User,
    ) -> AdminActionListItem:
        return AdminActionListItem(
            action_id=action.id,
            admin_user_id=action.admin_user_id,
            admin_telegram_id=admin_user.telegram_id,
            admin_username=admin_user.username,
            target_user_id=action.target_user_id,
            action_type=action.action_type,
            reason=action.reason,
            order_id=action.order_id,
            payment_id=action.payment_id,
            subscription_id=action.subscription_id,
            payload=action.payload,
            created_at=action.created_at,
        )