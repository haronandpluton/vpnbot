from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.common.enums import VPNNodeActualState, VPNNodeDesiredState
from app.services.subscription_node_access_state_service import (
    SubscriptionNodeAccessStateService,
)
from app.services.vpn_access_service import (
    VpnNodeProvisionResult,
    VpnNodeRenewalResult,
    VpnNodeStateChangeResult,
)


class FakeRepository:
    def __init__(self, existing: dict[tuple[int, str], object] | None = None) -> None:
        self.existing = existing or {}
        self.get_calls: list[tuple[int, str]] = []
        self.create_calls: list[dict] = []
        self.set_desired_calls: list[tuple[object, VPNNodeDesiredState]] = []
        self.mark_enabled_calls: list[object] = []
        self.mark_disabled_calls: list[object] = []
        self.mark_renewal_succeeded_calls: list[object] = []
        self.mark_error_calls: list[tuple[object, str]] = []

    async def get_by_subscription_and_node_for_update(
        self,
        subscription_id: int,
        node_code: str,
    ):
        self.get_calls.append((subscription_id, node_code))
        return self.existing.get((subscription_id, node_code))

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        record = SimpleNamespace(**kwargs)
        self.existing[(kwargs["subscription_id"], kwargs["node_code"])] = record
        return record

    async def set_desired_state(self, record, desired_state):
        self.set_desired_calls.append((record, desired_state))
        record.desired_state = desired_state
        return record

    async def mark_enabled(self, record):
        self.mark_enabled_calls.append(record)
        record.actual_state = VPNNodeActualState.ENABLED
        record.last_error = None
        record.retry_count = 0
        return record

    async def mark_disabled(self, record):
        self.mark_disabled_calls.append(record)
        record.actual_state = VPNNodeActualState.DISABLED
        record.last_error = None
        record.retry_count = 0
        record.disabled_at = object()
        return record

    async def mark_renewal_succeeded(self, record):
        self.mark_renewal_succeeded_calls.append(record)
        record.actual_state = VPNNodeActualState.ENABLED
        record.last_error = None
        record.retry_count = 0
        record.disabled_at = None
        return record

    async def mark_error(self, record, *, error_message):
        self.mark_error_calls.append((record, error_message))
        record.actual_state = VPNNodeActualState.ERROR
        record.last_error = error_message
        record.retry_count = getattr(record, "retry_count", 0) + 1
        return record


def make_service(repository: FakeRepository) -> SubscriptionNodeAccessStateService:
    service = SubscriptionNodeAccessStateService.__new__(
        SubscriptionNodeAccessStateService
    )
    service.repository = repository
    return service


@pytest.mark.asyncio
async def test_initialize_pending_creates_one_row_for_each_configured_node():
    repository = FakeRepository()
    service = make_service(repository)

    records = await service.initialize_pending(
        subscription_id=41,
        node_codes=("frankfurt", "netherlands", "sweden"),
    )

    assert [record.node_code for record in records] == [
        "frankfurt",
        "netherlands",
        "sweden",
    ]
    assert repository.create_calls == [
        {
            "subscription_id": 41,
            "node_code": "frankfurt",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        },
        {
            "subscription_id": 41,
            "node_code": "netherlands",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        },
        {
            "subscription_id": 41,
            "node_code": "sweden",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        },
    ]


@pytest.mark.asyncio
async def test_initialize_pending_is_idempotent_and_does_not_reset_actual_state():
    existing = SimpleNamespace(
        subscription_id=41,
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.DISABLED,
        actual_state=VPNNodeActualState.ERROR,
        last_error="temporary failure",
        retry_count=2,
    )
    repository = FakeRepository({(41, "frankfurt"): existing})
    service = make_service(repository)

    records = await service.initialize_pending(
        subscription_id=41,
        node_codes=("frankfurt", "frankfurt"),
    )

    assert records == (existing,)
    assert repository.create_calls == []
    assert repository.set_desired_calls == [
        (existing, VPNNodeDesiredState.ENABLED)
    ]
    assert existing.actual_state == VPNNodeActualState.ERROR
    assert existing.last_error == "temporary failure"
    assert existing.retry_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("subscription_id", "node_codes", "message"),
    [
        (0, ("frankfurt",), "subscription_id must be positive"),
        (41, (), "At least one VPN node is required"),
        (41, (" ",), "VPN node code must not be empty"),
    ],
)
async def test_initialize_pending_rejects_invalid_input(
    subscription_id,
    node_codes,
    message,
):
    service = make_service(FakeRepository())

    with pytest.raises(ValueError, match=message):
        await service.initialize_pending(
            subscription_id=subscription_id,
            node_codes=node_codes,
        )


@pytest.mark.asyncio
async def test_record_provisioning_results_marks_each_node_independently():
    frankfurt = SimpleNamespace(
        subscription_id=41,
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.ENABLED,
        actual_state=VPNNodeActualState.PENDING,
        last_error=None,
        retry_count=0,
    )
    netherlands = SimpleNamespace(
        subscription_id=41,
        node_code="netherlands",
        desired_state=VPNNodeDesiredState.ENABLED,
        actual_state=VPNNodeActualState.PENDING,
        last_error=None,
        retry_count=0,
    )
    repository = FakeRepository(
        {
            (41, "frankfurt"): frankfurt,
            (41, "netherlands"): netherlands,
        }
    )
    service = make_service(repository)

    records = await service.record_provisioning_results(
        subscription_id=41,
        results=(
            VpnNodeProvisionResult(node_name="frankfurt", enabled=True),
            VpnNodeProvisionResult(
                node_name="netherlands",
                enabled=False,
                error="temporary 3x-ui failure",
            ),
        ),
    )

    assert records == (frankfurt, netherlands)
    assert repository.mark_enabled_calls == [frankfurt]
    assert repository.mark_error_calls == [
        (netherlands, "temporary 3x-ui failure")
    ]
    assert frankfurt.actual_state == VPNNodeActualState.ENABLED
    assert frankfurt.retry_count == 0
    assert netherlands.actual_state == VPNNodeActualState.ERROR
    assert netherlands.last_error == "temporary 3x-ui failure"
    assert netherlands.retry_count == 1


@pytest.mark.asyncio
async def test_record_provisioning_results_creates_missing_row_and_truncates_error():
    repository = FakeRepository()
    service = make_service(repository)
    long_error = "x" * 1200

    records = await service.record_provisioning_results(
        subscription_id=41,
        results=(
            VpnNodeProvisionResult(
                node_name="future-node",
                enabled=False,
                error=long_error,
            ),
        ),
    )

    assert len(records) == 1
    assert repository.create_calls == [
        {
            "subscription_id": 41,
            "node_code": "future-node",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        }
    ]
    assert len(repository.mark_error_calls[0][1]) == 1000


@pytest.mark.asyncio
async def test_record_provisioning_results_allows_empty_retry_result():
    repository = FakeRepository()
    service = make_service(repository)

    assert await service.record_provisioning_results(
        subscription_id=41,
        results=(),
    ) == ()


@pytest.mark.asyncio
async def test_record_successful_renewal_results_clears_failure_state():
    provisioned_at = object()
    record = SimpleNamespace(
        subscription_id=41,
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.ENABLED,
        actual_state=VPNNodeActualState.ERROR,
        last_error="temporary renewal failure",
        retry_count=3,
        provisioned_at=provisioned_at,
        disabled_at=object(),
    )
    repository = FakeRepository({(41, "frankfurt"): record})
    service = make_service(repository)

    records = await service.record_successful_renewal_results(
        subscription_id=41,
        results=(
            VpnNodeRenewalResult(node_name="frankfurt", updated=True),
            VpnNodeRenewalResult(
                node_name="netherlands",
                updated=False,
                error="panel unavailable",
            ),
        ),
    )

    assert records == (record,)
    assert repository.mark_renewal_succeeded_calls == [record]
    assert repository.get_calls == [(41, "frankfurt")]
    assert record.actual_state == VPNNodeActualState.ENABLED
    assert record.last_error is None
    assert record.retry_count == 0
    assert record.disabled_at is None
    assert record.provisioned_at is provisioned_at


@pytest.mark.asyncio
async def test_record_successful_renewal_results_creates_missing_node_row():
    repository = FakeRepository()
    service = make_service(repository)

    records = await service.record_successful_renewal_results(
        subscription_id=41,
        results=(
            VpnNodeRenewalResult(node_name="future-node", updated=True),
        ),
    )

    assert len(records) == 1
    assert repository.create_calls == [
        {
            "subscription_id": 41,
            "node_code": "future-node",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        }
    ]
    assert repository.mark_renewal_succeeded_calls == [records[0]]


@pytest.mark.asyncio
async def test_record_successful_renewal_results_rejects_invalid_subscription_id():
    service = make_service(FakeRepository())

    with pytest.raises(ValueError, match="subscription_id must be positive"):
        await service.record_successful_renewal_results(
            subscription_id=0,
            results=(),
        )

@pytest.mark.asyncio
async def test_record_failed_renewal_results_marks_only_failed_nodes():
    frankfurt = SimpleNamespace(
        subscription_id=41,
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.ENABLED,
        actual_state=VPNNodeActualState.ENABLED,
        last_error=None,
        retry_count=0,
    )
    netherlands = SimpleNamespace(
        subscription_id=41,
        node_code="netherlands",
        desired_state=VPNNodeDesiredState.ENABLED,
        actual_state=VPNNodeActualState.ENABLED,
        last_error=None,
        retry_count=2,
    )
    repository = FakeRepository(
        {
            (41, "frankfurt"): frankfurt,
            (41, "netherlands"): netherlands,
        }
    )
    service = make_service(repository)

    records = await service.record_failed_renewal_results(
        subscription_id=41,
        results=(
            VpnNodeRenewalResult(node_name="frankfurt", updated=True),
            VpnNodeRenewalResult(
                node_name="netherlands",
                updated=False,
                error="panel unavailable",
            ),
        ),
    )

    assert records == (netherlands,)
    assert repository.get_calls == [(41, "netherlands")]
    assert repository.mark_error_calls == [
        (netherlands, "panel unavailable")
    ]
    assert netherlands.actual_state == VPNNodeActualState.ERROR
    assert netherlands.last_error == "panel unavailable"
    assert netherlands.retry_count == 3
    assert frankfurt.actual_state == VPNNodeActualState.ENABLED


@pytest.mark.asyncio
async def test_record_failed_renewal_results_creates_missing_row_and_truncates_error():
    repository = FakeRepository()
    service = make_service(repository)

    records = await service.record_failed_renewal_results(
        subscription_id=41,
        results=(
            VpnNodeRenewalResult(
                node_name="future-node",
                updated=False,
                error="x" * 1200,
            ),
        ),
    )

    assert len(records) == 1
    assert repository.create_calls == [
        {
            "subscription_id": 41,
            "node_code": "future-node",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        }
    ]
    assert len(repository.mark_error_calls[0][1]) == 1000
    assert records[0].actual_state == VPNNodeActualState.ERROR
    assert records[0].retry_count == 1


@pytest.mark.asyncio
async def test_record_failed_renewal_results_uses_default_error_message():
    repository = FakeRepository()
    service = make_service(repository)

    await service.record_failed_renewal_results(
        subscription_id=41,
        results=(
            VpnNodeRenewalResult(
                node_name="netherlands",
                updated=False,
            ),
        ),
    )

    assert repository.mark_error_calls[0][1] == "VPN node renewal failed"


@pytest.mark.asyncio
async def test_record_failed_renewal_results_rejects_invalid_subscription_id():
    service = make_service(FakeRepository())

    with pytest.raises(ValueError, match="subscription_id must be positive"):
        await service.record_failed_renewal_results(
            subscription_id=0,
            results=(),
        )


@pytest.mark.asyncio
async def test_record_successful_enable_results_restores_enabled_state():
    provisioned_at = object()
    record = SimpleNamespace(
        subscription_id=41,
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.DISABLED,
        actual_state=VPNNodeActualState.ERROR,
        last_error="temporary enable failure",
        retry_count=3,
        provisioned_at=provisioned_at,
        disabled_at=object(),
    )
    repository = FakeRepository({(41, "frankfurt"): record})
    service = make_service(repository)

    records = await service.record_successful_enable_results(
        subscription_id=41,
        results=(
            VpnNodeStateChangeResult(
                node_name="frankfurt",
                succeeded=True,
            ),
            VpnNodeStateChangeResult(
                node_name="netherlands",
                succeeded=False,
                error="panel unavailable",
            ),
        ),
    )

    assert records == (record,)
    assert repository.get_calls == [(41, "frankfurt")]
    assert repository.set_desired_calls == [
        (record, VPNNodeDesiredState.ENABLED)
    ]
    assert repository.mark_renewal_succeeded_calls == [record]
    assert record.desired_state == VPNNodeDesiredState.ENABLED
    assert record.actual_state == VPNNodeActualState.ENABLED
    assert record.last_error is None
    assert record.retry_count == 0
    assert record.disabled_at is None
    assert record.provisioned_at is provisioned_at


@pytest.mark.asyncio
async def test_record_successful_enable_results_creates_missing_node_row():
    repository = FakeRepository()
    service = make_service(repository)

    records = await service.record_successful_enable_results(
        subscription_id=41,
        results=(
            VpnNodeStateChangeResult(
                node_name="future-node",
                succeeded=True,
            ),
        ),
    )

    assert len(records) == 1
    assert repository.create_calls == [
        {
            "subscription_id": 41,
            "node_code": "future-node",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        }
    ]
    assert repository.mark_renewal_succeeded_calls == [records[0]]


@pytest.mark.asyncio
async def test_record_successful_enable_results_rejects_invalid_subscription_id():
    service = make_service(FakeRepository())

    with pytest.raises(ValueError, match="subscription_id must be positive"):
        await service.record_successful_enable_results(
            subscription_id=0,
            results=(),
        )

@pytest.mark.asyncio
async def test_record_failed_enable_results_marks_only_failed_nodes():
    successful = SimpleNamespace(
        subscription_id=41,
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.ENABLED,
        actual_state=VPNNodeActualState.ENABLED,
        last_error=None,
        retry_count=0,
    )
    failed = SimpleNamespace(
        subscription_id=41,
        node_code="netherlands",
        desired_state=VPNNodeDesiredState.DISABLED,
        actual_state=VPNNodeActualState.DISABLED,
        last_error=None,
        retry_count=2,
    )
    repository = FakeRepository(
        {
            (41, "frankfurt"): successful,
            (41, "netherlands"): failed,
        }
    )
    service = make_service(repository)

    records = await service.record_failed_enable_results(
        subscription_id=41,
        results=(
            VpnNodeStateChangeResult(
                node_name="frankfurt",
                succeeded=True,
            ),
            VpnNodeStateChangeResult(
                node_name="netherlands",
                succeeded=False,
                error="panel unavailable",
            ),
        ),
    )

    assert records == (failed,)
    assert repository.get_calls == [(41, "netherlands")]
    assert repository.set_desired_calls == [
        (failed, VPNNodeDesiredState.ENABLED)
    ]
    assert repository.mark_error_calls == [
        (failed, "panel unavailable")
    ]
    assert failed.desired_state == VPNNodeDesiredState.ENABLED
    assert failed.actual_state == VPNNodeActualState.ERROR
    assert failed.last_error == "panel unavailable"
    assert failed.retry_count == 3
    assert successful.actual_state == VPNNodeActualState.ENABLED


@pytest.mark.asyncio
async def test_record_failed_enable_results_creates_missing_row_and_truncates_error():
    repository = FakeRepository()
    service = make_service(repository)

    records = await service.record_failed_enable_results(
        subscription_id=41,
        results=(
            VpnNodeStateChangeResult(
                node_name="future-node",
                succeeded=False,
                error="x" * 1200,
            ),
        ),
    )

    assert len(records) == 1
    assert repository.create_calls == [
        {
            "subscription_id": 41,
            "node_code": "future-node",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        }
    ]
    assert len(repository.mark_error_calls[0][1]) == 1000
    assert records[0].actual_state == VPNNodeActualState.ERROR
    assert records[0].retry_count == 1


@pytest.mark.asyncio
async def test_record_failed_enable_results_uses_default_error_message():
    repository = FakeRepository()
    service = make_service(repository)

    await service.record_failed_enable_results(
        subscription_id=41,
        results=(
            VpnNodeStateChangeResult(
                node_name="netherlands",
                succeeded=False,
            ),
        ),
    )

    assert repository.mark_error_calls[0][1] == "VPN node enable failed"


@pytest.mark.asyncio
async def test_record_failed_enable_results_rejects_invalid_subscription_id():
    service = make_service(FakeRepository())

    with pytest.raises(ValueError, match="subscription_id must be positive"):
        await service.record_failed_enable_results(
            subscription_id=0,
            results=(),
        )

@pytest.mark.asyncio
async def test_record_successful_disable_results_restores_disabled_state():
    provisioned_at = object()
    record = SimpleNamespace(
        subscription_id=41,
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.ENABLED,
        actual_state=VPNNodeActualState.ERROR,
        last_error="temporary disable failure",
        retry_count=3,
        provisioned_at=provisioned_at,
        disabled_at=None,
    )
    repository = FakeRepository({(41, "frankfurt"): record})
    service = make_service(repository)

    records = await service.record_successful_disable_results(
        subscription_id=41,
        results=(
            VpnNodeStateChangeResult(
                node_name="frankfurt",
                succeeded=True,
            ),
            VpnNodeStateChangeResult(
                node_name="netherlands",
                succeeded=False,
                error="panel unavailable",
            ),
        ),
    )

    assert records == (record,)
    assert repository.get_calls == [(41, "frankfurt")]
    assert repository.set_desired_calls == [
        (record, VPNNodeDesiredState.DISABLED)
    ]
    assert repository.mark_disabled_calls == [record]
    assert record.desired_state == VPNNodeDesiredState.DISABLED
    assert record.actual_state == VPNNodeActualState.DISABLED
    assert record.last_error is None
    assert record.retry_count == 0
    assert record.disabled_at is not None
    assert record.provisioned_at is provisioned_at


@pytest.mark.asyncio
async def test_record_successful_disable_results_creates_missing_node_row():
    repository = FakeRepository()
    service = make_service(repository)

    records = await service.record_successful_disable_results(
        subscription_id=41,
        results=(
            VpnNodeStateChangeResult(
                node_name="future-node",
                succeeded=True,
            ),
        ),
    )

    assert len(records) == 1
    assert repository.create_calls == [
        {
            "subscription_id": 41,
            "node_code": "future-node",
            "desired_state": VPNNodeDesiredState.DISABLED,
            "actual_state": VPNNodeActualState.PENDING,
        }
    ]
    assert repository.mark_disabled_calls == [records[0]]
    assert records[0].actual_state == VPNNodeActualState.DISABLED
    assert records[0].retry_count == 0


@pytest.mark.asyncio
async def test_record_successful_disable_results_rejects_invalid_subscription_id():
    service = make_service(FakeRepository())

    with pytest.raises(ValueError, match="subscription_id must be positive"):
        await service.record_successful_disable_results(
            subscription_id=0,
            results=(),
        )

@pytest.mark.asyncio
async def test_record_failed_disable_results_marks_only_failed_nodes():
    successful = SimpleNamespace(
        subscription_id=41,
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.DISABLED,
        actual_state=VPNNodeActualState.DISABLED,
        last_error=None,
        retry_count=0,
    )
    failed = SimpleNamespace(
        subscription_id=41,
        node_code="netherlands",
        desired_state=VPNNodeDesiredState.ENABLED,
        actual_state=VPNNodeActualState.ENABLED,
        last_error=None,
        retry_count=2,
    )
    repository = FakeRepository(
        {
            (41, "frankfurt"): successful,
            (41, "netherlands"): failed,
        }
    )
    service = make_service(repository)

    records = await service.record_failed_disable_results(
        subscription_id=41,
        results=(
            VpnNodeStateChangeResult(
                node_name="frankfurt",
                succeeded=True,
            ),
            VpnNodeStateChangeResult(
                node_name="netherlands",
                succeeded=False,
                error="panel unavailable",
            ),
        ),
    )

    assert records == (failed,)
    assert repository.get_calls == [(41, "netherlands")]
    assert repository.set_desired_calls == [
        (failed, VPNNodeDesiredState.DISABLED)
    ]
    assert repository.mark_error_calls == [
        (failed, "panel unavailable")
    ]
    assert failed.desired_state == VPNNodeDesiredState.DISABLED
    assert failed.actual_state == VPNNodeActualState.ERROR
    assert failed.last_error == "panel unavailable"
    assert failed.retry_count == 3
    assert successful.actual_state == VPNNodeActualState.DISABLED


@pytest.mark.asyncio
async def test_record_failed_disable_results_creates_missing_row_and_truncates_error():
    repository = FakeRepository()
    service = make_service(repository)

    records = await service.record_failed_disable_results(
        subscription_id=41,
        results=(
            VpnNodeStateChangeResult(
                node_name="future-node",
                succeeded=False,
                error="x" * 1200,
            ),
        ),
    )

    assert len(records) == 1
    assert repository.create_calls == [
        {
            "subscription_id": 41,
            "node_code": "future-node",
            "desired_state": VPNNodeDesiredState.DISABLED,
            "actual_state": VPNNodeActualState.PENDING,
        }
    ]
    assert len(repository.mark_error_calls[0][1]) == 1000
    assert records[0].desired_state == VPNNodeDesiredState.DISABLED
    assert records[0].actual_state == VPNNodeActualState.ERROR
    assert records[0].retry_count == 1


@pytest.mark.asyncio
async def test_record_failed_disable_results_uses_default_error_message():
    repository = FakeRepository()
    service = make_service(repository)

    await service.record_failed_disable_results(
        subscription_id=41,
        results=(
            VpnNodeStateChangeResult(
                node_name="netherlands",
                succeeded=False,
            ),
        ),
    )

    assert repository.mark_error_calls[0][1] == "VPN node disable failed"


@pytest.mark.asyncio
async def test_record_failed_disable_results_rejects_invalid_subscription_id():
    service = make_service(FakeRepository())

    with pytest.raises(ValueError, match="subscription_id must be positive"):
        await service.record_failed_disable_results(
            subscription_id=0,
            results=(),
        )
