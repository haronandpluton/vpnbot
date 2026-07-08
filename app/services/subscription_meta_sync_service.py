from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.database.models import Subscription
from app.database.repositories.system_errors import SystemErrorRecordRepository
from app.payment_core.enums.subscription_status import SubscriptionStatus

logger = logging.getLogger(__name__)

SUBSCRIPTION_META_SYNC_ERROR_TYPE = "subscription_meta_sync_failed"
_SUBSCRIPTION_META_SYNC_LOCK = asyncio.Lock()
_SUBSCRIPTION_META_ERROR_LOCK = asyncio.Lock()


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


@dataclass
class SubscriptionMetaRetryResult:
    pending_count: int
    attempted: bool
    ok: bool
    resolved_count: int = 0
    error: str | None = None
    sync_result: SubscriptionMetaSyncResult | None = None


@dataclass(frozen=True)
class RemoteTarget:
    host: str
    path: str
    directory: str
    filename: str


class SubscriptionMetaSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.project_root = Path(__file__).resolve().parents[2]

    async def sync(self) -> SubscriptionMetaSyncResult:
        """
        Export and publish a complete metadata snapshot.

        The process-wide lock serializes snapshots inside one bot process so an
        older snapshot cannot finish after a newer one and overwrite it.
        """
        async with _SUBSCRIPTION_META_SYNC_LOCK:
            return await self._sync_and_resolve_pending_errors()

    async def sync_safely(
        self,
        *,
        entity_type: str,
        entity_id: int | None,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> SubscriptionMetaSafeSyncResult:
        """
        Best-effort post-commit hook.

        A failed ZA upload never rolls back the already committed payment or
        subscription change. One unresolved system_errors row acts as the
        durable retry marker for the latest complete snapshot.
        """
        async with _SUBSCRIPTION_META_SYNC_LOCK:
            try:
                sync_result = await self._sync_and_resolve_pending_errors()

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
                logger.exception(
                    "Subscription metadata sync failed: "
                    "entity_type=%s entity_id=%s reason=%s",
                    entity_type,
                    entity_id,
                    reason,
                )

                await self._record_sync_failure(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    reason=reason,
                    error_message=error_message,
                    payload=payload,
                )

                return SubscriptionMetaSafeSyncResult(
                    ok=False,
                    error=error_message,
                )

    async def retry_pending(self) -> SubscriptionMetaRetryResult:
        """Retry a previously failed snapshot without creating duplicate errors."""
        async with _SUBSCRIPTION_META_SYNC_LOCK:
            repository = SystemErrorRecordRepository(self.session)
            pending = await repository.get_unresolved_by_error_type(
                SUBSCRIPTION_META_SYNC_ERROR_TYPE
            )
            pending_ids = {error.id for error in pending}
            pending_count = len(pending_ids)
            await self.session.rollback()

            if pending_count == 0:
                return SubscriptionMetaRetryResult(
                    pending_count=0,
                    attempted=False,
                    ok=True,
                )

            try:
                sync_result = await self._sync_and_resolve_pending_errors()
                unresolved = await SystemErrorRecordRepository(
                    self.session
                ).get_unresolved_by_error_type(SUBSCRIPTION_META_SYNC_ERROR_TYPE)
                unresolved_ids = {error.id for error in unresolved}
                await self.session.rollback()
                resolved_count = len(pending_ids - unresolved_ids)

                return SubscriptionMetaRetryResult(
                    pending_count=pending_count,
                    attempted=True,
                    ok=resolved_count == pending_count,
                    resolved_count=resolved_count,
                    error=None
                    if resolved_count == pending_count
                    else "Metadata published, but retry markers remain unresolved.",
                    sync_result=sync_result,
                )
            except Exception as error:
                error_message = str(error)
                logger.exception(
                    "Background subscription metadata retry failed: pending_count=%s",
                    pending_count,
                )

                await self._record_sync_failure(
                    entity_type="subscription_metadata",
                    entity_id=None,
                    reason="background_retry",
                    error_message=error_message,
                    payload={"pending_count": pending_count},
                )

                return SubscriptionMetaRetryResult(
                    pending_count=pending_count,
                    attempted=True,
                    ok=False,
                    error=error_message,
                )

    async def _sync_and_resolve_pending_errors(
        self,
    ) -> SubscriptionMetaSyncResult:
        result = await self._sync_snapshot()

        try:
            await self._resolve_pending_sync_errors()
        except Exception:
            logger.exception(
                "Metadata snapshot published, but pending sync errors "
                "could not be marked resolved."
            )

        return result

    async def _sync_snapshot(self) -> SubscriptionMetaSyncResult:
        output_path = self._resolve_output_path()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data, skipped_count = await self._build_metadata()
        self._write_metadata_atomically(output_path, data)

        stdout, stderr = await self._upload(output_path)

        return SubscriptionMetaSyncResult(
            exported_count=len(data),
            skipped_count=skipped_count,
            output_path=str(output_path),
            remote_target=self.settings.subscription_meta_remote_target,
            stdout=stdout,
            stderr=stderr,
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

    async def _resolve_pending_sync_errors(self) -> int:
        """A successful full snapshot supersedes every older sync failure."""
        try:
            await self.session.rollback()
            repository = SystemErrorRecordRepository(self.session)
            pending = await repository.get_unresolved_by_error_type(
                SUBSCRIPTION_META_SYNC_ERROR_TYPE
            )

            if not pending:
                await self.session.rollback()
                return 0

            await repository.mark_many_resolved(pending)
            await self.session.commit()
            return len(pending)
        except Exception:
            await self.session.rollback()
            raise

    async def _record_sync_failure(
        self,
        *,
        entity_type: str,
        entity_id: int | None,
        reason: str,
        error_message: str,
        payload: dict[str, Any] | None,
    ) -> None:
        async with _SUBSCRIPTION_META_ERROR_LOCK:
            try:
                await self.session.rollback()
                repository = SystemErrorRecordRepository(self.session)
                pending = await repository.get_unresolved_by_error_type(
                    SUBSCRIPTION_META_SYNC_ERROR_TYPE
                )

                error_payload = json.dumps(
                    {
                        "reason": reason,
                        "error": error_message,
                        "remote_target": self.settings.subscription_meta_remote_target,
                        "payload": payload or {},
                    },
                    ensure_ascii=False,
                )

                if pending:
                    await repository.update_pending_failure(
                        pending[0],
                        entity_type=entity_type,
                        entity_id=entity_id,
                        error_message=error_message[:1000],
                        payload=error_payload,
                    )
                else:
                    await repository.create(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        error_type=SUBSCRIPTION_META_SYNC_ERROR_TYPE,
                        error_message=error_message[:1000],
                        payload=error_payload,
                    )

                await self.session.commit()
            except Exception:
                logger.exception("Failed to persist subscription metadata sync error.")
                await self.session.rollback()

    def _resolve_output_path(self) -> Path:
        configured = Path(self.settings.subscription_meta_output_path)

        if configured.is_absolute():
            return configured

        return self.project_root / configured

    @staticmethod
    def _to_unix_timestamp(value: datetime) -> int:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return int(value.timestamp())

    @staticmethod
    def _write_metadata_atomically(
        output_path: Path,
        data: dict[str, dict[str, int]],
    ) -> None:
        temporary_path = output_path.with_name(
            f".{output_path.name}.{uuid4().hex}.tmp"
        )

        try:
            temporary_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_path, output_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    async def _upload(self, output_path: Path) -> tuple[str, str]:
        remote_target_raw = self.settings.subscription_meta_remote_target.strip()

        if not remote_target_raw:
            raise RuntimeError(
                "SUBSCRIPTION_META_REMOTE_TARGET is not configured."
            )

        remote_target = self._parse_remote_target(remote_target_raw)
        temp_name = f".{remote_target.filename}.{uuid4().hex}.tmp"
        remote_temp_path = str(PurePosixPath(remote_target.directory) / temp_name)
        remote_temp_target = f"{remote_target.host}:{remote_temp_path}"
        common_args = self._ssh_common_args()

        scp_command = [
            "scp",
            *common_args,
            str(output_path),
            remote_temp_target,
        ]

        quoted_temp = shlex.quote(remote_temp_path)
        quoted_final = shlex.quote(remote_target.path)
        publish_command = (
            "set -eu; "
            f"python3 -m json.tool {quoted_temp} >/dev/null; "
            f"chmod 0660 {quoted_temp}; "
            f"mv -f {quoted_temp} {quoted_final}"
        )

        ssh_command = [
            "ssh",
            *common_args,
            remote_target.host,
            publish_command,
        ]

        try:
            scp_stdout, scp_stderr = await self._run_process(
                scp_command,
                operation="SCP upload",
            )
            ssh_stdout, ssh_stderr = await self._run_process(
                ssh_command,
                operation="Remote atomic publish",
            )
        except Exception:
            await self._cleanup_remote_temp(
                remote_target.host,
                remote_temp_path,
                common_args,
            )
            raise

        stdout = "\n".join(part for part in [scp_stdout, ssh_stdout] if part)
        stderr = "\n".join(part for part in [scp_stderr, ssh_stderr] if part)
        return stdout, stderr

    async def _cleanup_remote_temp(
        self,
        remote_host: str,
        remote_temp_path: str,
        common_args: list[str],
    ) -> None:
        cleanup_command = [
            "ssh",
            *common_args,
            remote_host,
            f"rm -f {shlex.quote(remote_temp_path)}",
        ]

        try:
            await self._run_process(
                cleanup_command,
                operation="Remote temp cleanup",
                timeout_seconds=min(
                    5,
                    self.settings.subscription_meta_sync_timeout_seconds,
                ),
            )
        except Exception:
            logger.warning(
                "Failed to remove temporary subscription metadata file: host=%s path=%s",
                remote_host,
                remote_temp_path,
                exc_info=True,
            )

    def _ssh_common_args(self) -> list[str]:
        args = [
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=10",
        ]

        if self.settings.subscription_meta_ssh_key:
            args.extend(["-i", self.settings.subscription_meta_ssh_key])

        return args

    async def _run_process(
        self,
        command: list[str],
        *,
        operation: str,
        timeout_seconds: float | None = None,
    ) -> tuple[str, str]:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                process.communicate(),
                timeout=(
                    self.settings.subscription_meta_sync_timeout_seconds
                    if timeout_seconds is None
                    else timeout_seconds
                ),
            )
        except asyncio.TimeoutError as error:
            process.kill()
            await process.wait()
            raise RuntimeError(f"{operation} timeout.") from error

        stdout = stdout_raw.decode("utf-8", errors="replace").strip()
        stderr = stderr_raw.decode("utf-8", errors="replace").strip()

        if process.returncode != 0:
            raise RuntimeError(
                f"{operation} failed. "
                f"returncode={process.returncode}; stderr={stderr}"
            )

        return stdout, stderr

    @staticmethod
    def _parse_remote_target(value: str) -> RemoteTarget:
        if "\n" in value or "\r" in value:
            raise ValueError("SUBSCRIPTION_META_REMOTE_TARGET contains a newline.")

        host, separator, path = value.partition(":")

        if not separator or not host or not path.startswith("/"):
            raise ValueError(
                "SUBSCRIPTION_META_REMOTE_TARGET must look like "
                "user@host:/absolute/path/file.json"
            )

        if re.fullmatch(r"[A-Za-z0-9_.@-]+", host) is None:
            raise ValueError("SUBSCRIPTION_META_REMOTE_TARGET has an invalid host.")

        if re.fullmatch(r"/[A-Za-z0-9_./-]+", path) is None:
            raise ValueError("SUBSCRIPTION_META_REMOTE_TARGET has an invalid path.")

        pure_path = PurePosixPath(path)
        filename = pure_path.name
        directory = str(pure_path.parent)

        if not filename or directory == ".":
            raise ValueError(
                "SUBSCRIPTION_META_REMOTE_TARGET must include an absolute file path."
            )

        return RemoteTarget(
            host=host,
            path=path,
            directory=directory,
            filename=filename,
        )
