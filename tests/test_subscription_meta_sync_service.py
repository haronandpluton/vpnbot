from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.subscription_meta_sync_service as meta_module
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.subscription_meta_sync_service import (
    SubscriptionMetaSafeSyncResult,
    SubscriptionMetaSyncResult,
    SubscriptionMetaSyncService,
)


class FakeScalarResult:
    def __init__(self, items) -> None:
        self.items = items

    def all(self):
        return self.items


class FakeExecuteResult:
    def __init__(self, items) -> None:
        self.items = items

    def scalars(self):
        return FakeScalarResult(self.items)


class FakeSession:
    def __init__(
        self,
        *,
        items=None,
        fail_rollback: bool = False,
        fail_commit: bool = False,
    ) -> None:
        self.items = items or []
        self.fail_rollback = fail_rollback
        self.fail_commit = fail_commit
        self.execute_calls = []
        self.rollback_count = 0
        self.commit_count = 0

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeExecuteResult(self.items)

    async def rollback(self) -> None:
        self.rollback_count += 1

        if self.fail_rollback:
            raise RuntimeError("rollback failed")

    async def commit(self) -> None:
        self.commit_count += 1

        if self.fail_commit:
            raise RuntimeError("commit failed")


class FakeSystemErrorRecordRepository:
    calls: list[dict] = []
    fail_create = False

    def __init__(self, session) -> None:
        self.session = session

    async def create(self, **kwargs):
        self.__class__.calls.append(kwargs)

        if self.__class__.fail_create:
            raise RuntimeError("system error create failed")

        return SimpleNamespace(id=900, **kwargs)


class FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: bytes = b"uploaded",
        stderr: bytes = b"",
        hang: bool = False,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.hang = hang
        self.kill_count = 0
        self.wait_count = 0
        self.communicate_count = 0

    async def communicate(self):
        self.communicate_count += 1

        if self.hang:
            await asyncio.sleep(10)

        return self.stdout, self.stderr

    def kill(self) -> None:
        self.kill_count += 1

    async def wait(self):
        self.wait_count += 1


def make_settings(
    *,
    output_path: str = "subscriptions_meta.json",
    remote_target: str = "",
    ssh_key: str = "",
    timeout: float = 1,
):
    return SimpleNamespace(
        subscription_meta_output_path=output_path,
        subscription_meta_remote_target=remote_target,
        subscription_meta_ssh_key=ssh_key,
        subscription_meta_sync_timeout_seconds=timeout,
    )


def make_subscription(
    *,
    uuid: str | None = "uuid-1",
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    expires_at=None,
):
    return SimpleNamespace(
        uuid=uuid,
        status=status,
        expires_at=expires_at,
    )


def make_service(
    *,
    session: FakeSession | None = None,
    settings=None,
    project_root: Path | None = None,
):
    service = SubscriptionMetaSyncService.__new__(SubscriptionMetaSyncService)
    service.session = session or FakeSession()
    service.settings = settings or make_settings()
    service.project_root = project_root or Path("/tmp/project-root")
    return service


@pytest.fixture(autouse=True)
def reset_system_error_repo(monkeypatch):
    FakeSystemErrorRecordRepository.calls = []
    FakeSystemErrorRecordRepository.fail_create = False

    monkeypatch.setattr(
        meta_module,
        "SystemErrorRecordRepository",
        FakeSystemErrorRecordRepository,
    )


@pytest.mark.asyncio
async def test_build_metadata_exports_active_and_expired_subscriptions_and_skips_missing_uuid_or_expiry():
    active_expires_at = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    expired_expires_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    session = FakeSession(
        items=[
            make_subscription(
                uuid="active-uuid",
                status=SubscriptionStatus.ACTIVE,
                expires_at=active_expires_at,
            ),
            make_subscription(
                uuid="expired-uuid",
                status=SubscriptionStatus.EXPIRED,
                expires_at=expired_expires_at,
            ),
            make_subscription(
                uuid=None,
                status=SubscriptionStatus.ACTIVE,
                expires_at=active_expires_at,
            ),
            make_subscription(
                uuid="no-expiry-uuid",
                status=SubscriptionStatus.ACTIVE,
                expires_at=None,
            ),
        ]
    )
    service = make_service(session=session)

    data, skipped_count = await service._build_metadata()

    assert skipped_count == 2
    assert set(data) == {"active-uuid", "expired-uuid"}
    assert data["active-uuid"] == {
        "expire": int(active_expires_at.timestamp()),
        "upload": 0,
        "download": 0,
        "total": 0,
    }
    assert data["expired-uuid"] == {
        "expire": int(expired_expires_at.timestamp()),
        "upload": 0,
        "download": 0,
        "total": 0,
    }
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_build_metadata_exports_disabled_subscription_as_already_expired_even_without_expires_at():
    before = int(datetime.now(timezone.utc).timestamp())
    session = FakeSession(
        items=[
            make_subscription(
                uuid="disabled-uuid",
                status=SubscriptionStatus.DISABLED,
                expires_at=None,
            )
        ]
    )
    service = make_service(session=session)

    data, skipped_count = await service._build_metadata()

    after = int(datetime.now(timezone.utc).timestamp())

    assert skipped_count == 0
    assert set(data) == {"disabled-uuid"}
    assert data["disabled-uuid"]["upload"] == 0
    assert data["disabled-uuid"]["download"] == 0
    assert data["disabled-uuid"]["total"] == 0
    assert data["disabled-uuid"]["expire"] >= before - 60
    assert data["disabled-uuid"]["expire"] <= after - 60


def test_resolve_output_path_returns_absolute_path_unchanged(tmp_path):
    absolute_path = tmp_path / "meta" / "subscriptions.json"
    service = make_service(
        settings=make_settings(output_path=str(absolute_path)),
        project_root=tmp_path / "project",
    )

    assert service._resolve_output_path() == absolute_path


def test_resolve_output_path_resolves_relative_path_under_project_root(tmp_path):
    service = make_service(
        settings=make_settings(output_path="deploy/subscriptions.json"),
        project_root=tmp_path / "project",
    )

    assert service._resolve_output_path() == tmp_path / "project" / "deploy/subscriptions.json"


def test_to_unix_timestamp_treats_naive_datetime_as_utc():
    value = datetime(2026, 7, 5, 12, 0, 0)

    assert SubscriptionMetaSyncService._to_unix_timestamp(value) == int(
        value.replace(tzinfo=timezone.utc).timestamp()
    )


@pytest.mark.asyncio
async def test_sync_writes_metadata_file_creates_parent_directory_and_returns_upload_result(tmp_path):
    output_path = tmp_path / "nested" / "subscriptions_meta.json"
    service = make_service(
        settings=make_settings(output_path=str(output_path), remote_target=""),
        project_root=tmp_path,
    )

    async def fake_build_metadata():
        return (
            {
                "uuid-1": {
                    "expire": 123,
                    "upload": 0,
                    "download": 0,
                    "total": 0,
                }
            },
            2,
        )

    async def fake_upload(path):
        assert path == output_path
        return "upload stdout", "upload stderr"

    service._build_metadata = fake_build_metadata
    service._upload = fake_upload

    result = await service.sync()

    assert result == SubscriptionMetaSyncResult(
        exported_count=1,
        skipped_count=2,
        output_path=str(output_path),
        remote_target="",
        stdout="upload stdout",
        stderr="upload stderr",
    )
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "uuid-1": {
            "expire": 123,
            "upload": 0,
            "download": 0,
            "total": 0,
        }
    }


@pytest.mark.asyncio
async def test_sync_safely_success_returns_ok_and_rolls_back_read_transaction(tmp_path):
    session = FakeSession()
    sync_result = SubscriptionMetaSyncResult(
        exported_count=1,
        skipped_count=0,
        output_path=str(tmp_path / "meta.json"),
        remote_target="",
        stdout="ok",
        stderr="",
    )
    service = make_service(session=session)

    async def fake_sync():
        return sync_result

    service.sync = fake_sync

    result = await service.sync_safely(
        entity_type="subscription",
        entity_id=50,
        reason="manual_extend_subscription",
        payload={"subscription_id": 50},
    )

    assert result == SubscriptionMetaSafeSyncResult(ok=True, sync_result=sync_result)
    assert session.rollback_count == 1
    assert session.commit_count == 0
    assert FakeSystemErrorRecordRepository.calls == []


@pytest.mark.asyncio
async def test_sync_safely_success_ignores_rollback_failure_after_select_transaction(tmp_path):
    session = FakeSession(fail_rollback=True)
    sync_result = SubscriptionMetaSyncResult(
        exported_count=1,
        skipped_count=0,
        output_path=str(tmp_path / "meta.json"),
        remote_target="",
        stdout="ok",
        stderr="",
    )
    service = make_service(session=session)

    async def fake_sync():
        return sync_result

    service.sync = fake_sync

    result = await service.sync_safely(
        entity_type="subscription",
        entity_id=50,
        reason="manual_extend_subscription",
        payload=None,
    )

    assert result.ok is True
    assert result.error is None
    assert result.sync_result is sync_result
    assert session.rollback_count == 1
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_sync_safely_failure_records_system_error_and_commits():
    session = FakeSession()
    service = make_service(
        session=session,
        settings=make_settings(remote_target="root@example:/opt/subscriptions.json"),
    )

    async def failing_sync():
        raise RuntimeError("scp unavailable")

    service.sync = failing_sync

    result = await service.sync_safely(
        entity_type="subscription",
        entity_id=50,
        reason="manual_disable_subscription",
        payload={"subscription_id": 50, "uuid": "uuid-1"},
    )

    assert result == SubscriptionMetaSafeSyncResult(ok=False, error="scp unavailable")
    assert session.rollback_count == 1
    assert session.commit_count == 1
    assert len(FakeSystemErrorRecordRepository.calls) == 1

    call = FakeSystemErrorRecordRepository.calls[0]
    assert call["entity_type"] == "subscription"
    assert call["entity_id"] == 50
    assert call["error_type"] == "subscription_meta_sync_failed"
    assert call["error_message"] == "scp unavailable"

    payload = json.loads(call["payload"])
    assert payload == {
        "reason": "manual_disable_subscription",
        "error": "scp unavailable",
        "remote_target": "root@example:/opt/subscriptions.json",
        "payload": {"subscription_id": 50, "uuid": "uuid-1"},
    }


@pytest.mark.asyncio
async def test_sync_safely_failure_truncates_error_message_for_system_error_record():
    session = FakeSession()
    service = make_service(session=session)
    long_error = "x" * 1200

    async def failing_sync():
        raise RuntimeError(long_error)

    service.sync = failing_sync

    result = await service.sync_safely(
        entity_type="subscription",
        entity_id=50,
        reason="test",
        payload=None,
    )

    assert result.ok is False
    assert result.error == long_error
    assert len(FakeSystemErrorRecordRepository.calls[0]["error_message"]) == 1000
    assert FakeSystemErrorRecordRepository.calls[0]["error_message"] == "x" * 1000
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_sync_safely_failure_still_returns_error_when_error_recording_fails():
    session = FakeSession()
    service = make_service(session=session)
    FakeSystemErrorRecordRepository.fail_create = True

    async def failing_sync():
        raise RuntimeError("scp unavailable")

    service.sync = failing_sync

    result = await service.sync_safely(
        entity_type="subscription",
        entity_id=50,
        reason="manual_disable_subscription",
        payload=None,
    )

    assert result == SubscriptionMetaSafeSyncResult(ok=False, error="scp unavailable")
    assert session.rollback_count == 2
    assert session.commit_count == 0
    assert len(FakeSystemErrorRecordRepository.calls) == 1


@pytest.mark.asyncio
async def test_upload_with_empty_remote_target_does_not_call_scp(tmp_path):
    output_path = tmp_path / "subscriptions_meta.json"
    service = make_service(
        settings=make_settings(remote_target="   "),
    )

    stdout, stderr = await service._upload(output_path)

    assert stdout == f"Local metadata file written: {output_path}"
    assert stderr == ""


@pytest.mark.asyncio
async def test_upload_builds_scp_command_with_ssh_key_and_returns_decoded_output(monkeypatch, tmp_path):
    output_path = tmp_path / "subscriptions_meta.json"
    process = FakeProcess(stdout=b"done\n", stderr=b"warn\n")
    calls = []

    async def fake_create_subprocess_exec(*args, stdout, stderr):
        calls.append({"args": args, "stdout": stdout, "stderr": stderr})
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    service = make_service(
        settings=make_settings(
            remote_target="root@example:/opt/subscriptions.json",
            ssh_key="/root/.ssh/id_ed25519",
            timeout=5,
        )
    )

    stdout, stderr = await service._upload(output_path)

    assert stdout == "done"
    assert stderr == "warn"
    assert process.communicate_count == 1
    assert calls == [
        {
            "args": (
                "scp",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-i",
                "/root/.ssh/id_ed25519",
                str(output_path),
                "root@example:/opt/subscriptions.json",
            ),
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
    ]


@pytest.mark.asyncio
async def test_upload_raises_when_scp_returns_nonzero(monkeypatch, tmp_path):
    output_path = tmp_path / "subscriptions_meta.json"
    process = FakeProcess(returncode=1, stdout=b"", stderr=b"permission denied\n")

    async def fake_create_subprocess_exec(*args, stdout, stderr):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    service = make_service(
        settings=make_settings(remote_target="root@example:/opt/subscriptions.json")
    )

    with pytest.raises(RuntimeError, match="SCP upload failed") as exc:
        await service._upload(output_path)

    assert "returncode=1" in str(exc.value)
    assert "permission denied" in str(exc.value)


@pytest.mark.asyncio
async def test_upload_timeout_kills_process_and_raises_runtime_error(monkeypatch, tmp_path):
    output_path = tmp_path / "subscriptions_meta.json"
    process = FakeProcess(hang=True)

    async def fake_create_subprocess_exec(*args, stdout, stderr):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    service = make_service(
        settings=make_settings(
            remote_target="root@example:/opt/subscriptions.json",
            timeout=0.01,
        )
    )

    with pytest.raises(RuntimeError, match="SCP upload timeout"):
        await service._upload(output_path)

    assert process.kill_count == 1
    assert process.wait_count == 1