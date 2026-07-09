from __future__ import annotations

from datetime import datetime, timezone

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
        stmt = (
            select(SystemErrorRecord)
            .where(SystemErrorRecord.is_resolved.is_(False))
            .order_by(SystemErrorRecord.id.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_unresolved_by_error_type(
        self,
        error_type: str,
    ) -> list[SystemErrorRecord]:
        stmt = (
            select(SystemErrorRecord)
            .where(
                SystemErrorRecord.is_resolved.is_(False),
                SystemErrorRecord.error_type == error_type,
            )
            .order_by(SystemErrorRecord.id.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_unresolved_by_entity_and_error_type(
        self,
        *,
        entity_type: str,
        entity_id: int | None,
        error_type: str,
    ) -> SystemErrorRecord | None:
        if entity_id is None:
            entity_id_filter = SystemErrorRecord.entity_id.is_(None)
        else:
            entity_id_filter = SystemErrorRecord.entity_id == entity_id

        stmt = (
            select(SystemErrorRecord)
            .where(
                SystemErrorRecord.is_resolved.is_(False),
                SystemErrorRecord.entity_type == entity_type,
                entity_id_filter,
                SystemErrorRecord.error_type == error_type,
            )
            .order_by(SystemErrorRecord.id.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_pending_failure(
        self,
        error: SystemErrorRecord,
        *,
        entity_type: str,
        entity_id: int | None,
        error_message: str,
        payload: str | None,
    ) -> SystemErrorRecord:
        error.entity_type = entity_type
        error.entity_id = entity_id
        error.error_message = error_message
        error.payload = payload
        error.retry_count += 1
        await self.session.flush()
        return error

    async def mark_resolved(self, error: SystemErrorRecord) -> SystemErrorRecord:
        error.is_resolved = True
        error.resolved_at = datetime.now(timezone.utc)
        await self.session.flush()
        return error

    async def mark_many_resolved(
        self,
        errors: list[SystemErrorRecord],
    ) -> list[SystemErrorRecord]:
        resolved_at = datetime.now(timezone.utc)

        for error in errors:
            error.is_resolved = True
            error.resolved_at = resolved_at

        if errors:
            await self.session.flush()

        return errors
