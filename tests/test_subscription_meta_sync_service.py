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
    update_calls: list[dict] = []
    resolved_calls: list[list] = []
    pending: list = []
    fail_create = False

    def __init__(self, session) -> None:
        self.session = session

    async def create(self, **kwargs):
        self.__class__.calls.append(kwargs)

        if self.__class__.fail_create:
            raise RuntimeError("system error create failed")

        record = SimpleNamespace(
            id=900,
            retry_count=0,
            is_resolved=False,
            resolved_at=None,
            **kwargs,
        )
        self.__class__.pending.append(record)
        return record

    async def get_unresolved_by_error_type(self, error_type):
        return [
            item
            for item in self.__class__.pending
            if item.error_type == error_type and not item.is_resolved
        ]

    async def update_pending_failure(self, error, **kwargs):
        self.__class__.update_calls.append({"error": error, **kwargs})
        error.entity_type = kwargs["entity_type"]
        error.entity_id = kwargs["entity_id"]
        error.error_message = kwargs["error_message"]
        error.payload = kwargs["payload"]
        error.retry_count += 1
        return error

    async def mark_many_resolved(self, errors):
        self.__class__.resolved_calls.append(list(errors))
        for error in errors:
            error.is_resolved = True
        return errors


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
    FakeSystemErrorRecordRepository.update_calls = []
    FakeSystemErrorRecordRepository.resolved_calls = []
    FakeSystemErrorRecordRepository.pending = []
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

    service._sync_and_resolve_pending_errors = fake_sync

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

    service._sync_and_resolve_pending_errors = fake_sync

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

    service._sync_and_resolve_pending_errors = failing_sync

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

    service._sync_and_resolve_pending_errors = failing_sync

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

    service._sync_and_resolve_pending_errors = failing_sync

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
async def test_upload_with_empty_remote_target_fails_closed(tmp_path):
    output_path = tmp_path / "subscriptions_meta.json"
    service = make_service(
        settings=make_settings(remote_target="   "),
    )

    with pytest.raises(
        RuntimeError,
        match="SUBSCRIPTION_META_REMOTE_TARGET is not configured",
    ):
        await service._upload(output_path)


@pytest.mark.asyncio
async def test_upload_builds_scp_command_with_ssh_key_and_returns_decoded_output(monkeypatch, tmp_path):
    output_path = tmp_path / "subscriptions_meta.json"
    scp_process = FakeProcess(stdout=b"uploaded\n", stderr=b"")
    publish_process = FakeProcess(stdout=b"published\n", stderr=b"warn\n")
    processes = iter([scp_process, publish_process])
    calls = []

    async def fake_create_subprocess_exec(*args, stdout, stderr):
        calls.append({"args": args, "stdout": stdout, "stderr": stderr})
        return next(processes)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    service = make_service(
        settings=make_settings(
            remote_target="root@example:/opt/subscriptions.json",
            ssh_key="/root/.ssh/id_ed25519",
            timeout=5,
        )
    )

    stdout, stderr = await service._upload(output_path)

    assert stdout == "uploaded\npublished"
    assert stderr == "warn"
    assert scp_process.communicate_count == 1
    assert publish_process.communicate_count == 1
    assert len(calls) == 2

    scp_args = calls[0]["args"]
    assert scp_args[:9] == (
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
        "-i",
        "/root/.ssh/id_ed25519",
    )
    assert scp_args[9] == str(output_path)
    assert scp_args[10].startswith(
        "root@example:/opt/.subscriptions.json."
    )
    assert scp_args[10].endswith(".tmp")

    ssh_args = calls[1]["args"]
    assert ssh_args[:9] == (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
        "-i",
        "/root/.ssh/id_ed25519",
    )
    assert ssh_args[9] == "root@example"
    assert "python3 -m json.tool" in ssh_args[10]
    assert "chmod 0660" in ssh_args[10]
    assert "mv -f" in ssh_args[10]
    assert "/opt/subscriptions.json" in ssh_args[10]


@pytest.mark.asyncio
async def test_upload_raises_when_scp_returns_nonzero(monkeypatch, tmp_path):
    output_path = tmp_path / "subscriptions_meta.json"
    scp_process = FakeProcess(
        returncode=1,
        stdout=b"",
        stderr=b"permission denied\n",
    )
    cleanup_process = FakeProcess()
    processes = iter([scp_process, cleanup_process])

    async def fake_create_subprocess_exec(*args, stdout, stderr):
        return next(processes)

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
    scp_process = FakeProcess(hang=True)
    cleanup_process = FakeProcess()
    processes = iter([scp_process, cleanup_process])

    async def fake_create_subprocess_exec(*args, stdout, stderr):
        return next(processes)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    service = make_service(
        settings=make_settings(
            remote_target="root@example:/opt/subscriptions.json",
            timeout=0.01,
        )
    )

    with pytest.raises(RuntimeError, match="SCP upload timeout"):
        await service._upload(output_path)

    assert scp_process.kill_count == 1
    assert scp_process.wait_count == 1

@pytest.mark.asyncio
async def test_sync_safely_reuses_existing_pending_error_instead_of_creating_duplicate():
    existing = SimpleNamespace(
        id=1,
        entity_type="subscription",
        entity_id=10,
        error_type="subscription_meta_sync_failed",
        error_message="first failure",
        payload=None,
        retry_count=0,
        is_resolved=False,
        resolved_at=None,
    )
    FakeSystemErrorRecordRepository.pending = [existing]
    session = FakeSession()
    service = make_service(session=session)

    async def failing_sync():
        raise RuntimeError("second failure")

    service._sync_and_resolve_pending_errors = failing_sync

    result = await service.sync_safely(
        entity_type="order",
        entity_id=25,
        reason="post_payment_subscription_change",
        payload={"order_id": 25},
    )

    assert result.ok is False
    assert FakeSystemErrorRecordRepository.calls == []
    assert len(FakeSystemErrorRecordRepository.update_calls) == 1
    assert existing.entity_type == "order"
    assert existing.entity_id == 25
    assert existing.error_message == "second failure"
    assert existing.retry_count == 1
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_sync_success_marks_all_pending_sync_errors_resolved(tmp_path):
    first = SimpleNamespace(
        id=1,
        error_type="subscription_meta_sync_failed",
        is_resolved=False,
    )
    second = SimpleNamespace(
        id=2,
        error_type="subscription_meta_sync_failed",
        is_resolved=False,
    )
    FakeSystemErrorRecordRepository.pending = [first, second]
    session = FakeSession()
    output_path = tmp_path / "subscriptions_meta.json"
    service = make_service(
        session=session,
        settings=make_settings(output_path=str(output_path)),
    )

    async def fake_build_metadata():
        return {}, 0

    async def fake_upload(path):
        assert path == output_path
        return "ok", ""

    service._build_metadata = fake_build_metadata
    service._upload = fake_upload

    result = await service.sync()

    assert result.exported_count == 0
    assert first.is_resolved is True
    assert second.is_resolved is True
    assert FakeSystemErrorRecordRepository.resolved_calls == [[first, second]]
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_retry_pending_skips_when_no_unresolved_sync_error():
    session = FakeSession()
    service = make_service(session=session)

    result = await service.retry_pending()

    assert result.pending_count == 0
    assert result.attempted is False
    assert result.ok is True


@pytest.mark.asyncio
async def test_retry_pending_success_returns_resolved_count():
    pending = SimpleNamespace(
        id=1,
        error_type="subscription_meta_sync_failed",
        is_resolved=False,
    )
    FakeSystemErrorRecordRepository.pending = [pending]
    session = FakeSession()
    service = make_service(session=session)
    sync_result = SubscriptionMetaSyncResult(
        exported_count=3,
        skipped_count=0,
        output_path="meta.json",
        remote_target="root@example:/opt/meta.json",
        stdout="ok",
        stderr="",
    )

    async def fake_sync():
        pending.is_resolved = True
        return sync_result

    service._sync_and_resolve_pending_errors = fake_sync

    result = await service.retry_pending()

    assert result.pending_count == 1
    assert result.attempted is True
    assert result.ok is True
    assert result.resolved_count == 1
    assert result.sync_result is sync_result


@pytest.mark.asyncio
async def test_retry_pending_failure_updates_existing_error_without_duplicate():
    pending = SimpleNamespace(
        id=1,
        entity_type="subscription",
        entity_id=10,
        error_type="subscription_meta_sync_failed",
        error_message="first",
        payload=None,
        retry_count=2,
        is_resolved=False,
        resolved_at=None,
    )
    FakeSystemErrorRecordRepository.pending = [pending]
    session = FakeSession()
    service = make_service(session=session)

    async def failing_sync():
        raise RuntimeError("still unavailable")

    service._sync_and_resolve_pending_errors = failing_sync

    result = await service.retry_pending()

    assert result.pending_count == 1
    assert result.attempted is True
    assert result.ok is False
    assert result.error == "still unavailable"
    assert FakeSystemErrorRecordRepository.calls == []
    assert len(FakeSystemErrorRecordRepository.update_calls) == 1
    assert pending.retry_count == 3
    assert pending.entity_type == "subscription_metadata"
    assert pending.entity_id is None


def test_parse_remote_target_accepts_expected_target():
    target = SubscriptionMetaSyncService._parse_remote_target(
        "vpnadmin@139.84.251.197:/opt/vpn-subscription/subscriptions_meta.json"
    )

    assert target.host == "vpnadmin@139.84.251.197"
    assert target.path == "/opt/vpn-subscription/subscriptions_meta.json"
    assert target.directory == "/opt/vpn-subscription"
    assert target.filename == "subscriptions_meta.json"


@pytest.mark.parametrize(
    "value",
    [
        "missing-colon",
        "host:relative/path.json",
        "host:/path with space/meta.json",
        "host;touch-pwned:/opt/meta.json",
        "host:/opt/meta.json\nextra",
    ],
)
def test_parse_remote_target_rejects_unsafe_or_invalid_target(value):
    with pytest.raises(ValueError):
        SubscriptionMetaSyncService._parse_remote_target(value)
