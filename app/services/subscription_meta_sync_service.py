from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.database.models import Subscription
from app.database.repositories.system_errors import SystemErrorRecordRepository
from app.payment_core.enums.subscription_status import SubscriptionStatus


@dataclass
class SubscriptionMetaSyncResult:
    exported_count: int
    skipped_count: int
    output_path: str
    remote_target: str
    stdout: str
    stderr: str


@dataclass
class SubscriptionMetaSafeSyncResult:
    ok: bool
    error: str | None = None
    sync_result: SubscriptionMetaSyncResult | None = None


class SubscriptionMetaSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.project_root = Path(__file__).resolve().parents[2]

    async def sync(self) -> SubscriptionMetaSyncResult:
        output_path = self._resolve_output_path()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data, skipped_count = await self._build_metadata()

        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        stdout, stderr = await self._upload(output_path)

        return SubscriptionMetaSyncResult(
            exported_count=len(data),
            skipped_count=skipped_count,
            output_path=str(output_path),
            remote_target=self.settings.subscription_meta_remote_target,
            stdout=stdout,
            stderr=stderr,
        )

    async def sync_safely(
        self,
        *,
        entity_type: str,
        entity_id: int | None,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> SubscriptionMetaSafeSyncResult:
        """
        Non-critical sync hook.

        Used after subscription status/date changes.
        Must not break payment/subscription flow if SCP or VPS is unavailable.
        """
        try:
            sync_result = await self.sync()

            # sync() performs SELECTs, so SQLAlchemy may have an open read transaction.
            # Close it because this method is called after the main business commit.
            try:
                await self.session.rollback()
            except Exception:
                pass

            return SubscriptionMetaSafeSyncResult(
                ok=True,
                sync_result=sync_result,
            )

        except Exception as error:
            error_message = str(error)

            try:
                await self.session.rollback()

                error_payload = {
                    "reason": reason,
                    "error": error_message,
                    "remote_target": self.settings.subscription_meta_remote_target,
                    "payload": payload or {},
                }

                await SystemErrorRecordRepository(self.session).create(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_type="subscription_meta_sync_failed",
                    error_message=error_message[:1000],
                    payload=json.dumps(error_payload, ensure_ascii=False),
                )

                await self.session.commit()

            except Exception:
                await self.session.rollback()

            return SubscriptionMetaSafeSyncResult(
                ok=False,
                error=error_message,
            )

    async def _build_metadata(self) -> tuple[dict[str, dict[str, int]], int]:
        stmt = select(Subscription).where(
            Subscription.status.in_(
                [
                    SubscriptionStatus.ACTIVE,
                    SubscriptionStatus.EXPIRED,
                    SubscriptionStatus.DISABLED,
                ]
            )
        )

        result = await self.session.execute(stmt)
        subscriptions = result.scalars().all()

        data: dict[str, dict[str, int]] = {}
        skipped_count = 0
        now = datetime.now(timezone.utc)
        disabled_expire = int(now.timestamp()) - 60

        for subscription in subscriptions:
            if not subscription.uuid:
                skipped_count += 1
                continue

            if subscription.status == SubscriptionStatus.DISABLED:
                expire = disabled_expire
            else:
                if subscription.expires_at is None:
                    skipped_count += 1
                    continue

                expire = self._to_unix_timestamp(subscription.expires_at)

            data[str(subscription.uuid)] = {
                "expire": expire,
                "upload": 0,
                "download": 0,
                "total": 0,
            }

        return data, skipped_count

    def _resolve_output_path(self) -> Path:
        configured = Path(self.settings.subscription_meta_output_path)

        if configured.is_absolute():
            return configured

        return self.project_root / configured

    @staticmethod
    def _to_unix_timestamp(value) -> int:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return int(value.timestamp())

    async def _upload(self, output_path: Path) -> tuple[str, str]:
        remote_target = self.settings.subscription_meta_remote_target.strip()

        if not remote_target:
            return (
                f"Local metadata file written: {output_path}",
                "",
            )

        command = [
            "scp",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]

        if self.settings.subscription_meta_ssh_key:
            command.extend(["-i", self.settings.subscription_meta_ssh_key])

        command.extend(
            [
                str(output_path),
                remote_target,
            ]
        )

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                process.communicate(),
                timeout=self.settings.subscription_meta_sync_timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            process.kill()
            await process.wait()
            raise RuntimeError("SCP upload timeout.") from error

        stdout = stdout_raw.decode("utf-8", errors="replace").strip()
        stderr = stderr_raw.decode("utf-8", errors="replace").strip()

        if process.returncode != 0:
            raise RuntimeError(
                "SCP upload failed. "
                f"returncode={process.returncode}; stderr={stderr}"
            )

        return stdout, stderr