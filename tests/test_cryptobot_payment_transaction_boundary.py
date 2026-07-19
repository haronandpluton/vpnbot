from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.cryptobot_payment_service import CryptoBotPaymentService


class FakeSession:
    def __init__(self, call_log: list[str], *, fail_commit: bool = False) -> None:
        self.call_log = call_log
        self.fail_commit = fail_commit

    async def commit(self) -> None:
        self.call_log.append("commit")

        if self.fail_commit:
            raise RuntimeError("commit failed")


class FakeOrderRepository:
    def __init__(self, order, call_log: list[str]) -> None:
        self.order = order
        self.call_log = call_log

    async def get_by_id(self, order_id: int):
        self.call_log.append(f"get_order:{order_id}")
        return self.order


class FakeCryptoBotClient:
    def __init__(self, invoice, call_log: list[str]) -> None:
        self.invoice = invoice
        self.call_log = call_log
        self.invoice_ids: list[int] = []

    async def get_invoice(self, invoice_id: int):
        self.call_log.append(f"get_invoice:{invoice_id}")
        self.invoice_ids.append(invoice_id)
        return self.invoice


def make_service(
    *,
    session,
    order_repository,
    client,
) -> CryptoBotPaymentService:
    service = CryptoBotPaymentService.__new__(CryptoBotPaymentService)
    service.session = session
    service.order_repository = order_repository
    service._client = lambda: client
    return service


@pytest.mark.asyncio
async def test_sync_closes_read_transaction_before_provider_request():
    call_log: list[str] = []
    order = SimpleNamespace(
        id=23,
        destination_memo_tag="55822653",
        comment=None,
    )
    invoice = {
        "invoice_id": 55822653,
        "status": "active",
    }

    session = FakeSession(call_log)
    client = FakeCryptoBotClient(invoice, call_log)
    service = make_service(
        session=session,
        order_repository=FakeOrderRepository(order, call_log),
        client=client,
    )

    result = await service.sync_paid_invoice_and_activate(23)

    assert result == invoice
    assert call_log == [
        "get_order:23",
        "commit",
        "get_invoice:55822653",
    ]
    assert client.invoice_ids == [55822653]


@pytest.mark.asyncio
async def test_sync_does_not_call_provider_when_transaction_boundary_fails():
    call_log: list[str] = []
    order = SimpleNamespace(
        id=23,
        destination_memo_tag="55822653",
        comment=None,
    )

    session = FakeSession(call_log, fail_commit=True)
    client = FakeCryptoBotClient(
        {
            "invoice_id": 55822653,
            "status": "active",
        },
        call_log,
    )
    service = make_service(
        session=session,
        order_repository=FakeOrderRepository(order, call_log),
        client=client,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.sync_paid_invoice_and_activate(23)

    assert call_log == [
        "get_order:23",
        "commit",
    ]
    assert client.invoice_ids == []
