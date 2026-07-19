from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.services.cryptobot_background_sync_scheduler as scheduler_module
from app.services.cryptobot_background_sync_scheduler import (
    CryptoBotBackgroundSyncScheduler,
)


class FakeSession:
    def __init__(self, name: str) -> None:
        self.name = name
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeSessionContext:
    def __init__(self, session) -> None:
        self.session = session
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        self.exit_count += 1
        return False


class FakeSessionFactory:
    def __init__(self) -> None:
        self.contexts: list[FakeSessionContext] = []

    def __call__(self):
        context = FakeSessionContext(
            session=FakeSession(
                name=f"session-{len(self.contexts) + 1}"
            )
        )
        self.contexts.append(context)
        return context


class FakeBot:
    def __init__(self) -> None:
        self.send_calls: list[dict] = []

    async def send_message(self, *, chat_id: int, text: str) -> None:
        self.send_calls.append(
            {
                "chat_id": chat_id,
                "text": text,
            }
        )


class FakeOrderRepository:
    batches: dict[int, list[int]] = {}
    calls: list[dict] = []

    def __init__(self, session) -> None:
        self.session = session

    async def get_pending_cryptobot_order_ids(
        self,
        *,
        limit: int,
        after_id: int = 0,
    ) -> list[int]:
        self.__class__.calls.append(
            {
                "session": self.session,
                "limit": limit,
                "after_id": after_id,
            }
        )
        return list(self.__class__.batches.get(after_id, []))


class FakePaymentEventRepository:
    batches: dict[int, list[SimpleNamespace]] = {}
    calls: list[dict] = []

    def __init__(self, session) -> None:
        self.session = session

    async def get_pending_cryptobot_notifications(
        self,
        *,
        limit: int,
        after_event_id: int = 0,
    ):
        self.__class__.calls.append(
            {
                "session": self.session,
                "limit": limit,
                "after_event_id": after_event_id,
            }
        )
        return list(
            self.__class__.batches.get(after_event_id, [])
        )


class FakeSystemErrorRecordRepository:
    pending_by_order: dict[int, SimpleNamespace] = {}
    lookup_calls: list[dict] = []
    create_calls: list[dict] = []
    update_calls: list[dict] = []
    resolve_calls: list[object] = []
    fail_create = False

    def __init__(self, session) -> None:
        self.session = session

    async def get_unresolved_by_entity_and_error_type(self, **kwargs):
        self.__class__.lookup_calls.append(
            {
                "session": self.session,
                **kwargs,
            }
        )
        return self.__class__.pending_by_order.get(
            kwargs["entity_id"]
        )

    async def create(self, **kwargs):
        if self.__class__.fail_create:
            raise RuntimeError("system_errors unavailable")

        self.__class__.create_calls.append(
            {
                "session": self.session,
                **kwargs,
            }
        )
        record = SimpleNamespace(
            id=900 + len(self.__class__.create_calls),
            retry_count=0,
            is_resolved=False,
            **kwargs,
        )
        self.__class__.pending_by_order[kwargs["entity_id"]] = record
        return record

    async def update_pending_failure(self, error, **kwargs):
        self.__class__.update_calls.append(
            {
                "session": self.session,
                "error": error,
                **kwargs,
            }
        )
        error.entity_type = kwargs["entity_type"]
        error.entity_id = kwargs["entity_id"]
        error.error_message = kwargs["error_message"]
        error.payload = kwargs["payload"]
        error.retry_count += 1
        return error

    async def mark_resolved(self, error):
        self.__class__.resolve_calls.append(error)
        error.is_resolved = True
        return error


class FakeCryptoBotPaymentService:
    calls: list[dict] = []
    errors: dict[int, BaseException] = {}

    def __init__(self, session) -> None:
        self.session = session

    async def sync_paid_invoice_and_activate(self, order_id: int):
        self.__class__.calls.append(
            {
                "session": self.session,
                "order_id": order_id,
            }
        )

        error = self.__class__.errors.get(order_id)
        if error is not None:
            raise error

        return None


class FakeNotificationService:
    calls: list[dict] = []
    results: dict[int, SimpleNamespace] = {}
    errors: dict[int, BaseException] = {}

    def __init__(self, session) -> None:
        self.session = session

    async def deliver(
        self,
        *,
        event_id: int,
        order_id: int,
        telegram_id: int,
        send_message,
    ):
        self.__class__.calls.append(
            {
                "session": self.session,
                "event_id": event_id,
                "order_id": order_id,
                "telegram_id": telegram_id,
            }
        )

        error = self.__class__.errors.get(event_id)
        if error is not None:
            raise error

        result = self.__class__.results.get(
            event_id,
            SimpleNamespace(
                attempted=True,
                delivered=True,
                persisted=True,
                reason=None,
            ),
        )

        if result.delivered:
            await send_message(f"notification:{event_id}")

        return result


def make_settings(
    *,
    cryptobot_enabled: bool = True,
    background_enabled: bool = True,
    batch_size: int = 25,
):
    return SimpleNamespace(
        cryptobot_enabled=cryptobot_enabled,
        cryptobot_background_sync_enabled=background_enabled,
        cryptobot_background_sync_interval_seconds=20,
        cryptobot_background_sync_initial_delay_seconds=0,
        cryptobot_background_sync_batch_size=batch_size,
    )


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch):
    FakeOrderRepository.batches = {}
    FakeOrderRepository.calls = []

    FakePaymentEventRepository.batches = {}
    FakePaymentEventRepository.calls = []

    FakeSystemErrorRecordRepository.pending_by_order = {}
    FakeSystemErrorRecordRepository.lookup_calls = []
    FakeSystemErrorRecordRepository.create_calls = []
    FakeSystemErrorRecordRepository.update_calls = []
    FakeSystemErrorRecordRepository.resolve_calls = []
    FakeSystemErrorRecordRepository.fail_create = False

    FakeCryptoBotPaymentService.calls = []
    FakeCryptoBotPaymentService.errors = {}

    FakeNotificationService.calls = []
    FakeNotificationService.results = {}
    FakeNotificationService.errors = {}

    monkeypatch.setattr(
        scheduler_module,
        "OrderRepository",
        FakeOrderRepository,
    )
    monkeypatch.setattr(
        scheduler_module,
        "PaymentEventRepository",
        FakePaymentEventRepository,
    )
    monkeypatch.setattr(
        scheduler_module,
        "SystemErrorRecordRepository",
        FakeSystemErrorRecordRepository,
    )
    monkeypatch.setattr(
        scheduler_module,
        "CryptoBotPaymentService",
        FakeCryptoBotPaymentService,
    )
    monkeypatch.setattr(
        scheduler_module,
        "CryptoBotPaymentNotificationService",
        FakeNotificationService,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_settings",
        make_settings,
    )


@pytest.mark.asyncio
async def test_scheduler_returns_immediately_when_disabled(
    monkeypatch,
):
    monkeypatch.setattr(
        scheduler_module,
        "get_settings",
        lambda: make_settings(background_enabled=False),
    )

    session_factory = FakeSessionFactory()
    scheduler = CryptoBotBackgroundSyncScheduler(
        session_factory,
        FakeBot(),
    )

    await scheduler.run_forever()

    assert session_factory.contexts == []


@pytest.mark.asyncio
async def test_run_once_processes_orders_then_notifications():
    FakeOrderRepository.batches = {
        0: [10, 20],
    }
    FakePaymentEventRepository.batches = {
        0: [
            SimpleNamespace(
                event_id=100,
                order_id=10,
                telegram_id=555,
            )
        ],
    }

    session_factory = FakeSessionFactory()
    bot = FakeBot()
    scheduler = CryptoBotBackgroundSyncScheduler(
        session_factory,
        bot,
    )

    result = await scheduler.run_once()

    assert [call["order_id"] for call in FakeCryptoBotPaymentService.calls] == [
        10,
        20,
    ]
    assert [call["event_id"] for call in FakeNotificationService.calls] == [
        100,
    ]

    assert bot.send_calls == [
        {
            "chat_id": 555,
            "text": "notification:100",
        }
    ]

    assert result.orders_selected == 2
    assert result.orders_checked == 2
    assert result.order_failures == 0

    assert result.notifications_selected == 1
    assert result.notifications_attempted == 1
    assert result.notifications_delivered == 1
    assert result.notifications_persisted == 1
    assert result.notifications_skipped == 0
    assert result.notification_failures == 0

    assert len(session_factory.contexts) == 5
    assert all(
        context.enter_count == 1 and context.exit_count == 1
        for context in session_factory.contexts
    )


@pytest.mark.asyncio
async def test_item_failures_do_not_stop_remaining_work():
    FakeOrderRepository.batches = {
        0: [10, 20],
    }
    FakeCryptoBotPaymentService.errors = {
        10: RuntimeError("provider unavailable"),
    }

    FakePaymentEventRepository.batches = {
        0: [
            SimpleNamespace(
                event_id=100,
                order_id=10,
                telegram_id=555,
            ),
            SimpleNamespace(
                event_id=200,
                order_id=20,
                telegram_id=777,
            ),
        ],
    }
    FakeNotificationService.errors = {
        100: RuntimeError("telegram unavailable"),
    }

    scheduler = CryptoBotBackgroundSyncScheduler(
        FakeSessionFactory(),
        FakeBot(),
    )

    result = await scheduler.run_once()

    assert [call["order_id"] for call in FakeCryptoBotPaymentService.calls] == [
        10,
        20,
    ]
    assert [call["event_id"] for call in FakeNotificationService.calls] == [
        100,
        200,
    ]

    assert result.orders_checked == 1
    assert result.order_failures == 1
    assert result.notifications_persisted == 1
    assert result.notification_failures == 1


@pytest.mark.asyncio
async def test_unavailable_notification_claim_is_skipped():
    FakeOrderRepository.batches = {
        0: [],
    }
    FakePaymentEventRepository.batches = {
        0: [
            SimpleNamespace(
                event_id=100,
                order_id=10,
                telegram_id=555,
            )
        ],
    }
    FakeNotificationService.results = {
        100: SimpleNamespace(
            attempted=False,
            delivered=False,
            persisted=False,
            reason="not_claimed",
        )
    }

    bot = FakeBot()
    scheduler = CryptoBotBackgroundSyncScheduler(
        FakeSessionFactory(),
        bot,
    )

    result = await scheduler.run_once()

    assert result.notifications_selected == 1
    assert result.notifications_attempted == 0
    assert result.notifications_skipped == 1
    assert result.notification_failures == 0
    assert bot.send_calls == []


@pytest.mark.asyncio
async def test_order_cursor_wraps_after_reaching_end():
    FakeOrderRepository.batches = {
        0: [10, 20],
        20: [],
    }
    FakePaymentEventRepository.batches = {
        0: [],
    }

    scheduler = CryptoBotBackgroundSyncScheduler(
        FakeSessionFactory(),
        FakeBot(),
    )

    await scheduler.run_once()
    await scheduler.run_once()

    assert [
        call["after_id"]
        for call in FakeOrderRepository.calls
    ] == [
        0,
        20,
        0,
    ]


@pytest.mark.asyncio
async def test_notification_cursor_wraps_after_reaching_end():
    notification = SimpleNamespace(
        event_id=100,
        order_id=10,
        telegram_id=555,
    )

    FakeOrderRepository.batches = {
        0: [],
    }
    FakePaymentEventRepository.batches = {
        0: [notification],
        100: [],
    }

    scheduler = CryptoBotBackgroundSyncScheduler(
        FakeSessionFactory(),
        FakeBot(),
    )

    await scheduler.run_once()
    await scheduler.run_once()

    assert [
        call["after_event_id"]
        for call in FakePaymentEventRepository.calls
    ] == [
        0,
        100,
        0,
    ]


@pytest.mark.asyncio
async def test_cancellation_stops_scheduler_without_processing_next_phase():
    FakeOrderRepository.batches = {
        0: [10],
    }
    FakeCryptoBotPaymentService.errors = {
        10: asyncio.CancelledError(),
    }
    FakePaymentEventRepository.batches = {
        0: [
            SimpleNamespace(
                event_id=100,
                order_id=10,
                telegram_id=555,
            )
        ],
    }

    scheduler = CryptoBotBackgroundSyncScheduler(
        FakeSessionFactory(),
        FakeBot(),
    )

    with pytest.raises(asyncio.CancelledError):
        await scheduler.run_once()

    assert FakeNotificationService.calls == []
    assert FakePaymentEventRepository.calls == []


@pytest.mark.asyncio
async def test_invoice_sync_failure_creates_durable_system_error():
    FakeOrderRepository.batches = {
        0: [10],
    }
    FakeCryptoBotPaymentService.errors = {
        10: RuntimeError("provider unavailable"),
    }
    FakePaymentEventRepository.batches = {
        0: [],
    }

    scheduler = CryptoBotBackgroundSyncScheduler(
        FakeSessionFactory(),
        FakeBot(),
    )

    result = await scheduler.run_once()

    assert result.order_failures == 1
    assert len(FakeSystemErrorRecordRepository.create_calls) == 1

    created = FakeSystemErrorRecordRepository.create_calls[0]
    assert created["entity_type"] == "order"
    assert created["entity_id"] == 10
    assert created["error_type"] == "cryptobot_invoice_sync_failed"
    assert "RuntimeError: provider unavailable" in created["error_message"]
    assert '"phase": "invoice_sync"' in created["payload"]


@pytest.mark.asyncio
async def test_repeated_invoice_sync_failure_updates_existing_error():
    pending = SimpleNamespace(
        id=500,
        entity_type="order",
        entity_id=10,
        retry_count=2,
        is_resolved=False,
        error_message="old",
        payload=None,
    )
    FakeSystemErrorRecordRepository.pending_by_order = {
        10: pending,
    }
    FakeOrderRepository.batches = {
        0: [10],
    }
    FakeCryptoBotPaymentService.errors = {
        10: RuntimeError("provider still unavailable"),
    }
    FakePaymentEventRepository.batches = {
        0: [],
    }

    scheduler = CryptoBotBackgroundSyncScheduler(
        FakeSessionFactory(),
        FakeBot(),
    )

    await scheduler.run_once()

    assert FakeSystemErrorRecordRepository.create_calls == []
    assert len(FakeSystemErrorRecordRepository.update_calls) == 1
    assert pending.retry_count == 3
    assert "provider still unavailable" in pending.error_message


@pytest.mark.asyncio
async def test_successful_invoice_sync_resolves_previous_error():
    pending = SimpleNamespace(
        id=500,
        entity_type="order",
        entity_id=10,
        retry_count=2,
        is_resolved=False,
        error_message="provider unavailable",
        payload=None,
    )
    FakeSystemErrorRecordRepository.pending_by_order = {
        10: pending,
    }
    FakeOrderRepository.batches = {
        0: [10],
    }
    FakePaymentEventRepository.batches = {
        0: [],
    }

    scheduler = CryptoBotBackgroundSyncScheduler(
        FakeSessionFactory(),
        FakeBot(),
    )

    result = await scheduler.run_once()

    assert result.orders_checked == 1
    assert result.order_failures == 0
    assert FakeSystemErrorRecordRepository.resolve_calls == [pending]
    assert pending.is_resolved is True


@pytest.mark.asyncio
async def test_system_error_write_failure_does_not_stop_other_orders():
    FakeOrderRepository.batches = {
        0: [10, 20],
    }
    FakeCryptoBotPaymentService.errors = {
        10: RuntimeError("provider unavailable"),
    }
    FakeSystemErrorRecordRepository.fail_create = True
    FakePaymentEventRepository.batches = {
        0: [],
    }

    scheduler = CryptoBotBackgroundSyncScheduler(
        FakeSessionFactory(),
        FakeBot(),
    )

    result = await scheduler.run_once()

    assert [
        call["order_id"]
        for call in FakeCryptoBotPaymentService.calls
    ] == [10, 20]
    assert result.orders_checked == 1
    assert result.order_failures == 1
