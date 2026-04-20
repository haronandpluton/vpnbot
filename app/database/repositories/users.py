from sqlalchemy import select

from app.database.models import User
from app.database.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get_by_id(self, user_id: int) -> User | None:
        stmt = select(User).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language_code: str | None = None,
        is_admin: bool = False,
    ) -> User:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            is_admin=is_admin,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_basic_info(
        self,
        user: User,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language_code: str | None,
    ) -> User:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.language_code = language_code
        await self.session.flush()
        return user