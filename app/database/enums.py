from sqlalchemy import Enum as SqlAlchemyEnum

from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.payment_status import PaymentStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus


def enum_values(enum_cls):
    return [item.value for item in enum_cls]


order_status_enum = SqlAlchemyEnum(
    OrderStatus,
    name="order_status_enum",
    values_callable=enum_values,
)

payment_status_enum = SqlAlchemyEnum(
    PaymentStatus,
    name="payment_status_enum",
    values_callable=enum_values,
)

payment_method_enum = SqlAlchemyEnum(
    PaymentMethod,
    name="payment_method_enum",
    values_callable=enum_values,
)

subscription_status_enum = SqlAlchemyEnum(
    SubscriptionStatus,
    name="subscription_status_enum",
    values_callable=enum_values,
)

currency_code_enum = SqlAlchemyEnum(
    CurrencyCode,
    name="currency_code_enum",
    values_callable=enum_values,
)

network_code_enum = SqlAlchemyEnum(
    NetworkCode,
    name="network_code_enum",
    values_callable=enum_values,
)

tariff_code_enum = SqlAlchemyEnum(
    TariffCode,
    name="tariff_code_enum",
    values_callable=enum_values,
)