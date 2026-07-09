from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod
from app.services.order_service import OrderService

class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def flush(self) -> None:
        self.flush_count += 1


class FakeUserRepository:
    def __init__(self, *, existing_user=None, fail_create: bool = False) -> None:
        self.existing_user = existing_user
        self.fail_create = fail_create
        self.get_calls: list[int] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.next_id = 10

    async def get_by_telegram_id(self, telegram_id: int):
        self.get_calls.append(telegram_id)
        return self.existing_user

    async def update_basic_info(
        self,
        *,
        user,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language_code: str | None,
    ):
        self.update_calls.append(
            {
                "user_id": user.id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "language_code": language_code,
            }
        )
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.language_code = language_code
        return user

    async def create(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language_code: str | None,
        is_admin: bool,
    ):
        if self.fail_create:
            raise RuntimeError("user create failed")

        self.create_calls.append(
            {
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "language_code": language_code,
                "is_admin": is_admin,
            }
        )
        user = SimpleNamespace(
            id=self.next_id,
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            is_admin=is_admin,
        )
        self.next_id += 1
        self.existing_user = user
        return user


class FakeOrderRepository:
    def __init__(self, *, active_waiting_order=None, orders_by_id=None) -> None:
        self.active_waiting_order = active_waiting_order
        self.orders_by_id = orders_by_id or {}
        self.get_active_calls: list[dict] = []
        self.get_by_id_calls: list[int] = []
        self.create_calls: list[dict] = []
        self.mark_expired_calls: list[int] = []
        self.created_orders: list[SimpleNamespace] = []
        self.next_id = 100

    async def get_active_waiting_order_by_user(
        self,
        user_id: int,
        tariff_code: TariffCode,
        payment_option_id: int,
    ):
        self.get_active_calls.append(
            {
                "user_id": user_id,
                "tariff_code": tariff_code,
                "payment_option_id": payment_option_id,
            }
        )
        return self.active_waiting_order

    async def get_by_id(self, order_id: int):
        self.get_by_id_calls.append(order_id)
        return self.orders_by_id.get(order_id)

    async def create(
        self,
        *,
        user_id: int,
        tariff_code: TariffCode,
        device_limit: int,
        duration_days: int,
        price_usd,
        payment_method: PaymentMethod,
        payment_option_id: int | None,
        expected_amount,
        expected_currency: CurrencyCode | None,
        expected_network: NetworkCode | None,
        destination_address: str | None,
        destination_memo_tag: str | None,
        expires_at: datetime,
        source: str = "bot",
        comment: str | None = None,
    ):
        self.create_calls.append(
            {
                "user_id": user_id,
                "tariff_code": tariff_code,
                "device_limit": device_limit,
                "duration_days": duration_days,
                "price_usd": price_usd,
                "payment_method": payment_method,
                "payment_option_id": payment_option_id,
                "expected_amount": expected_amount,
                "expected_currency": expected_currency,
                "expected_network": expected_network,
                "destination_address": destination_address,
                "destination_memo_tag": destination_memo_tag,
                "expires_at": expires_at,
                "source": source,
                "comment": comment,
            }
        )
        order = SimpleNamespace(
            id=self.next_id,
            user_id=user_id,
            status=OrderStatus.WAITING_PAYMENT,
            tariff_code=tariff_code,
            device_limit=device_limit,
            duration_days=duration_days,
            price_usd=price_usd,
            payment_method=payment_method,
            payment_option_id=payment_option_id,
            expected_amount=expected_amount,
            expected_currency=expected_currency,
            expected_network=expected_network,
            destination_address=destination_address,
            destination_memo_tag=destination_memo_tag,
            expires_at=expires_at,
            source=source,
            comment=comment,
        )
        self.next_id += 1
        self.created_orders.append(order)
        self.orders_by_id[order.id] = order
        return order

    async def mark_expired(self, order):
        self.mark_expired_calls.append(order.id)
        order.status = OrderStatus.EXPIRED
        return order


class FakePaymentOptionRepository:
    def __init__(self, options_by_code: dict[str, SimpleNamespace] | None = None) -> None:
        self.options_by_code = options_by_code or {}
        self.get_by_code_calls: list[str] = []

    async def get_by_code(self, code: str):
        self.get_by_code_calls.append(code)
        return self.options_by_code.get(code)


def make_user(
    *,
    user_id: int = 7,
    telegram_id: int = 123,
    username: str | None = "old_username",
):
    return SimpleNamespace(
        id=user_id,
        telegram_id=telegram_id,
        username=username,
        first_name="Old",
        last_name="Name",
        language_code="ru",
        is_admin=False,
    )


def make_payment_option(
    *,
    option_id: int = 5,
    code: str = "usdt_trc20",
    payment_method: PaymentMethod = PaymentMethod.CRYPTO,
    currency: CurrencyCode | None = CurrencyCode.USDT,
    network: NetworkCode | None = NetworkCode.TRC20,
):
    return SimpleNamespace(
        id=option_id,
        code=code,
        payment_method=payment_method,
        currency=currency,
        network=network,
    )


def make_order(
    *,
    order_id: int = 50,
    user_id: int = 7,
    status: OrderStatus = OrderStatus.WAITING_PAYMENT,
):
    return SimpleNamespace(
        id=order_id,
        user_id=user_id,
        status=status,
        paid_at=None,
        activated_at=None,
        failure_reason=None,
    )


def make_service(
    *,
    user_repository: FakeUserRepository | None = None,
    order_repository: FakeOrderRepository | None = None,
    payment_option_repository: FakePaymentOptionRepository | None = None,
    order_ttl_minutes: int = 15,
    admin_ids: list[int] | None = None,
):
    service = OrderService.__new__(OrderService)
    service.session = FakeSession()
    service.settings = SimpleNamespace(
        order_ttl_minutes=order_ttl_minutes,
        admin_ids=admin_ids or [],
    )
    service.user_repository = user_repository or FakeUserRepository()
    service.order_repository = order_repository or FakeOrderRepository()
    service.payment_option_repository = (
        payment_option_repository
        or FakePaymentOptionRepository({"usdt_trc20": make_payment_option()})
    )
    return service


@pytest.mark.asyncio
async def test_create_order_creates_user_and_waiting_payment_order_with_tariff_and_payment_option():
    payment_option = make_payment_option(
        option_id=5,
        code="usdt_trc20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDT,
        network=NetworkCode.TRC20,
    )
    user_repository = FakeUserRepository(existing_user=None)
    order_repository = FakeOrderRepository(active_waiting_order=None)
    payment_option_repository = FakePaymentOptionRepository(
        {"usdt_trc20": payment_option}
    )
    service = make_service(
        user_repository=user_repository,
        order_repository=order_repository,
        payment_option_repository=payment_option_repository,
        order_ttl_minutes=15,
    )

    before_call = datetime.now(UTC)
    order = await service.create_order(
        telegram_id=123,
        tariff_code=TariffCode.PERIOD_2_MONTHS,
        payment_option_code="usdt_trc20",
        username="ivan",
        first_name="Ivan",
        last_name="Redeemer",
        language_code="ru",
    )
    after_call = datetime.now(UTC)

    assert order.status == OrderStatus.WAITING_PAYMENT
    assert order.user_id == 10
    assert order.tariff_code == TariffCode.PERIOD_2_MONTHS
    assert order.device_limit == 1
    assert order.duration_days == 66
    assert order.price_usd == Decimal("7.50")
    assert order.payment_method == PaymentMethod.CRYPTO
    assert order.payment_option_id == 5
    assert order.expected_amount is None
    assert order.expected_currency == CurrencyCode.USDT
    assert order.expected_network == NetworkCode.TRC20
    assert order.destination_address is None
    assert order.destination_memo_tag is None
    assert order.source == "bot"
    assert order.comment is None
    assert order.expires_at >= before_call + timedelta(minutes=15)
    assert order.expires_at <= after_call + timedelta(minutes=15, seconds=1)

    assert user_repository.create_calls == [
        {
            "telegram_id": 123,
            "username": "ivan",
            "first_name": "Ivan",
            "last_name": "Redeemer",
            "language_code": "ru",
            "is_admin": False,
        }
    ]
    assert order_repository.get_active_calls == [
        {
            "user_id": 10,
            "tariff_code": TariffCode.PERIOD_2_MONTHS,
            "payment_option_id": 5,
        }
    ]
    assert len(order_repository.create_calls) == 1
    assert payment_option_repository.get_by_code_calls == ["usdt_trc20"]
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_create_order_updates_existing_user_before_order_creation():
    existing_user = make_user(user_id=7, telegram_id=123, username="old")
    user_repository = FakeUserRepository(existing_user=existing_user)
    order_repository = FakeOrderRepository(active_waiting_order=None)
    service = make_service(
        user_repository=user_repository,
        order_repository=order_repository,
    )

    order = await service.create_order(
        telegram_id=123,
        tariff_code=TariffCode.PERIOD_1_MONTH,
        payment_option_code="usdt_trc20",
        username="new_username",
        first_name="New",
        last_name="User",
        language_code="en",
    )

    assert order.user_id == 7
    assert existing_user.username == "new_username"
    assert existing_user.first_name == "New"
    assert existing_user.last_name == "User"
    assert existing_user.language_code == "en"
    assert user_repository.create_calls == []
    assert user_repository.update_calls == [
        {
            "user_id": 7,
            "username": "new_username",
            "first_name": "New",
            "last_name": "User",
            "language_code": "en",
        }
    ]
    assert order_repository.get_active_calls == [
        {
            "user_id": 7,
            "tariff_code": TariffCode.PERIOD_1_MONTH,
            "payment_option_id": 5,
        }
    ]
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_create_order_marks_new_user_as_admin_when_telegram_id_is_in_settings_admin_ids():
    user_repository = FakeUserRepository(existing_user=None)
    service = make_service(
        user_repository=user_repository,
        admin_ids=[123, 456],
    )

    await service.create_order(
        telegram_id=123,
        tariff_code=TariffCode.PERIOD_1_MONTH,
        payment_option_code="usdt_trc20",
    )

    assert user_repository.create_calls[0]["is_admin"] is True
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_create_order_reuses_matching_waiting_order_and_does_not_create_duplicate():
    existing_user = make_user(user_id=7, telegram_id=123)
    active_order = make_order(order_id=77, user_id=7, status=OrderStatus.WAITING_PAYMENT)
    user_repository = FakeUserRepository(existing_user=existing_user)
    order_repository = FakeOrderRepository(active_waiting_order=active_order)
    payment_option = make_payment_option(option_id=5, code="usdt_trc20")
    payment_option_repository = FakePaymentOptionRepository(
        {"usdt_trc20": payment_option}
    )
    service = make_service(
        user_repository=user_repository,
        order_repository=order_repository,
        payment_option_repository=payment_option_repository,
    )

    result = await service.create_order(
        telegram_id=123,
        tariff_code=TariffCode.PERIOD_1_MONTH,
        payment_option_code="usdt_trc20",
    )

    assert result is active_order
    assert order_repository.create_calls == []
    assert order_repository.get_active_calls == [
        {
            "user_id": 7,
            "tariff_code": TariffCode.PERIOD_1_MONTH,
            "payment_option_id": 5,
        }
    ]
    assert payment_option_repository.get_by_code_calls == ["usdt_trc20"]
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_create_order_does_not_reuse_non_active_or_expired_order_when_repository_returns_none():
    existing_user = make_user(user_id=7, telegram_id=123)
    expired_order = make_order(order_id=70, user_id=7, status=OrderStatus.EXPIRED)
    user_repository = FakeUserRepository(existing_user=existing_user)
    order_repository = FakeOrderRepository(
        active_waiting_order=None,
        orders_by_id={expired_order.id: expired_order},
    )
    service = make_service(
        user_repository=user_repository,
        order_repository=order_repository,
    )

    order = await service.create_order(
        telegram_id=123,
        tariff_code=TariffCode.PERIOD_1_MONTH,
        payment_option_code="usdt_trc20",
    )

    assert order is not expired_order
    assert order.status == OrderStatus.WAITING_PAYMENT
    assert order.id != expired_order.id
    assert len(order_repository.create_calls) == 1
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_create_order_with_unsupported_tariff_rolls_back_and_does_not_create_order():
    existing_user = make_user(user_id=7, telegram_id=123)
    order_repository = FakeOrderRepository(active_waiting_order=None)
    payment_option_repository = FakePaymentOptionRepository(
        {"usdt_trc20": make_payment_option()}
    )
    service = make_service(
        user_repository=FakeUserRepository(existing_user=existing_user),
        order_repository=order_repository,
        payment_option_repository=payment_option_repository,
    )

    with pytest.raises(ValueError, match="Unsupported tariff code"):
        await service.create_order(
            telegram_id=123,
            tariff_code="bad_tariff",
            payment_option_code="usdt_trc20",
        )

    assert order_repository.create_calls == []
    assert payment_option_repository.get_by_code_calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1


@pytest.mark.asyncio
async def test_create_order_with_missing_payment_option_rolls_back_and_does_not_create_order():
    existing_user = make_user(user_id=7, telegram_id=123)
    order_repository = FakeOrderRepository(active_waiting_order=None)
    payment_option_repository = FakePaymentOptionRepository({})
    service = make_service(
        user_repository=FakeUserRepository(existing_user=existing_user),
        order_repository=order_repository,
        payment_option_repository=payment_option_repository,
    )

    with pytest.raises(ValueError, match="Payment option not found in DB: missing_option"):
        await service.create_order(
            telegram_id=123,
            tariff_code=TariffCode.PERIOD_1_MONTH,
            payment_option_code="missing_option",
        )

    assert payment_option_repository.get_by_code_calls == ["missing_option"]
    assert order_repository.create_calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1


@pytest.mark.asyncio
async def test_create_order_with_telegram_stars_payment_option_sets_empty_currency_and_network():
    existing_user = make_user(user_id=7, telegram_id=123)
    stars_option = make_payment_option(
        option_id=9,
        code="telegram_stars",
        payment_method=PaymentMethod.TELEGRAM_STARS,
        currency=None,
        network=None,
    )
    order_repository = FakeOrderRepository(active_waiting_order=None)
    service = make_service(
        user_repository=FakeUserRepository(existing_user=existing_user),
        order_repository=order_repository,
        payment_option_repository=FakePaymentOptionRepository(
            {"telegram_stars": stars_option}
        ),
    )

    order = await service.create_order(
        telegram_id=123,
        tariff_code=TariffCode.PERIOD_3_MONTHS,
        payment_option_code="telegram_stars",
    )

    assert order.tariff_code == TariffCode.PERIOD_3_MONTHS
    assert order.device_limit == 1
    assert order.duration_days == 100
    assert order.price_usd == Decimal("11.00")
    assert order.payment_method == PaymentMethod.TELEGRAM_STARS
    assert order.payment_option_id == 9
    assert order.expected_currency is None
    assert order.expected_network is None
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_expire_order_marks_waiting_payment_order_expired_and_commits():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    order_repository = FakeOrderRepository(orders_by_id={23: order})
    service = make_service(order_repository=order_repository)

    result = await service.expire_order(23)

    assert result is order
    assert order.status == OrderStatus.EXPIRED
    assert order_repository.mark_expired_calls == [23]
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_expire_order_does_not_change_non_waiting_order_but_commits():
    order = make_order(order_id=23, status=OrderStatus.PAID)
    order_repository = FakeOrderRepository(orders_by_id={23: order})
    service = make_service(order_repository=order_repository)

    result = await service.expire_order(23)

    assert result is order
    assert order.status == OrderStatus.PAID
    assert order_repository.mark_expired_calls == []
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_expire_order_missing_order_returns_none_without_commit():
    order_repository = FakeOrderRepository(orders_by_id={})
    service = make_service(order_repository=order_repository)

    result = await service.expire_order(404)

    assert result is None
    assert order_repository.mark_expired_calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 0
