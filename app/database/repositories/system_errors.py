from sqlalchemy import select

from app.database.models import SystemErrorRecord
from app.database.repositories.base import BaseRepository


class SystemErrorRecordRepository(BaseRepository):
    async def create(
        self,
        entity_type: str,
        entity_id: int | None,
        error_type: str,
        error_message: str,
        payload: str | None = None,
    ) -> SystemErrorRecord:
        error = SystemErrorRecord(
            entity_type=entity_type,
            entity_id=entity_id,
            error_type=error_type,
            error_message=error_message,
            payload=payload,
        )
        self.session.add(error)
        await self.session.flush()
        return error

    async def get_unresolved(self) -> list[SystemErrorRecord]:
        stmt = select(SystemErrorRecord).where(SystemErrorRecord.is_resolved == False)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_resolved(self, error: SystemErrorRecord) -> SystemErrorRecord:
        error.is_resolved = True
        await self.session.flush()
        return error