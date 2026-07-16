from __future__ import annotations

import app.database.models as models_package
from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.database.enums import (
    currency_code_enum,
    enum_values,
    network_code_enum,
    order_status_enum,
    payment_method_enum,
    payment_status_enum,
    subscription_status_enum,
    tariff_code_enum,
)
from app.database.models import (
    AdminAction,
    Order,
    Payment,
    PaymentEvent,
    PaymentOption,
    Subscription,
    SystemErrorRecord,
    User,
    VPNServer,
)
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.payment_status import PaymentStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus


def column(model, name: str):
    return model.__table__.c[name]


def fk_targets(model, name: str) -> set[str]:
    return {fk.target_fullname for fk in column(model, name).foreign_keys}


def test_database_models_package_exports_all_domain_models():
    assert set(models_package.__all__) == {
        "User",
        "PaymentOption",
        "Order",
        "Payment",
        "PaymentEvent",
        "VPNServer",
        "Subscription",
        "AdminAction",
        "SystemErrorRecord",
    }
    assert models_package.User is User
    assert models_package.Payment is Payment
    assert models_package.Subscription is Subscription


def test_database_enum_values_follow_domain_state_machines():
    assert enum_values(OrderStatus) == [
        "created",
        "waiting_payment",
        "paid",
        "activated",
        "expired",
        "cancelled",
        "failed",
    ]
    assert enum_values(PaymentStatus) == [
        "new",
        "detected",
        "confirmed",
        "invalid",
        "duplicate",
        "expired",
        "error",
    ]
    assert enum_values(SubscriptionStatus) == [
        "inactive",
        "active",
        "expired",
        "disabled",
        "error",
    ]


def test_sqlalchemy_enums_store_string_values_not_python_names():
    assert order_status_enum.enums == enum_values(OrderStatus)
    assert payment_status_enum.enums == enum_values(PaymentStatus)
    assert payment_method_enum.enums == enum_values(PaymentMethod)
    assert subscription_status_enum.enums == enum_values(SubscriptionStatus)
    assert currency_code_enum.enums == enum_values(CurrencyCode)
    assert network_code_enum.enums == enum_values(NetworkCode)
    assert tariff_code_enum.enums == enum_values(TariffCode)


def test_user_model_has_unique_telegram_identity_and_admin_flags():
    assert User.__tablename__ == "users"
    assert column(User, "telegram_id").unique is True
    assert column(User, "telegram_id").index is True
    assert column(User, "telegram_id").nullable is False
    assert column(User, "is_admin").nullable is False
    assert str(column(User, "is_admin").server_default.arg) == "false"
    assert column(User, "is_blocked").nullable is False
    assert str(column(User, "is_blocked").server_default.arg) == "false"

    assert column(User, "trial_eligible").nullable is False
    assert column(User, "trial_eligible").default.arg is True
    assert str(column(User, "trial_eligible").server_default.arg) == "true"
    assert column(User, "trial_claimed_at").nullable is True


def test_payment_option_model_keeps_currency_network_as_separate_configured_option():
    assert PaymentOption.__tablename__ == "payment_options"
    assert column(PaymentOption, "code").unique is True
    assert column(PaymentOption, "code").index is True
    assert column(PaymentOption, "payment_method").index is True
    assert column(PaymentOption, "currency").index is True
    assert column(PaymentOption, "network").index is True
    assert column(PaymentOption, "is_active").nullable is False
    assert str(column(PaymentOption, "is_active").server_default.arg) == "true"


def test_order_model_contains_expected_payment_snapshot_and_status_indexes():
    assert Order.__tablename__ == "orders"
    assert fk_targets(Order, "user_id") == {"users.id"}
    assert fk_targets(Order, "payment_option_id") == {"payment_options.id"}
    assert column(Order, "status").index is True
    assert column(Order, "status").default.arg == OrderStatus.CREATED
    assert column(Order, "status").server_default.arg == OrderStatus.CREATED.value
    assert column(Order, "tariff_code").index is True
    assert column(Order, "payment_method").index is True
    assert column(Order, "expected_currency").index is True
    assert column(Order, "expected_network").index is True
    assert column(Order, "expires_at").index is True
    assert str(column(Order, "source").server_default.arg) == "'bot'"


def test_payment_model_has_unique_txid_and_provider_reference_for_idempotency():
    assert Payment.__tablename__ == "payments"
    assert fk_targets(Payment, "order_id") == {"orders.id"}
    assert fk_targets(Payment, "user_id") == {"users.id"}
    assert fk_targets(Payment, "payment_option_id") == {"payment_options.id"}
    assert column(Payment, "status").index is True
    assert column(Payment, "status").default.arg == PaymentStatus.NEW
    assert column(Payment, "status").server_default.arg == PaymentStatus.NEW.value
    assert column(Payment, "txid").unique is True
    assert column(Payment, "txid").index is True
    assert column(Payment, "provider_payment_id").unique is True
    assert column(Payment, "provider_payment_id").index is True
    assert column(Payment, "currency").index is True
    assert column(Payment, "network").index is True


def test_payment_event_model_persists_raw_provider_events_for_recovery():
    assert PaymentEvent.__tablename__ == "payment_events"
    assert fk_targets(PaymentEvent, "payment_id") == {"payments.id"}
    assert fk_targets(PaymentEvent, "order_id") == {"orders.id"}
    assert column(PaymentEvent, "event_type").index is True
    assert column(PaymentEvent, "external_event_id").index is True
    assert column(PaymentEvent, "txid").index is True
    assert column(PaymentEvent, "provider").index is True
    assert column(PaymentEvent, "processed").index is True
    assert column(PaymentEvent, "processed").default.arg is False
    assert str(column(PaymentEvent, "processed").server_default.arg) == "false"
    assert column(PaymentEvent, "processing_status").index is True


def test_subscription_model_has_stable_uuid_and_vpn_server_binding():
    assert Subscription.__tablename__ == "subscriptions"
    assert fk_targets(Subscription, "user_id") == {"users.id"}
    assert fk_targets(Subscription, "order_id") == {"orders.id"}
    assert fk_targets(Subscription, "vpn_server_id") == {"vpn_servers.id"}
    assert column(Subscription, "status").index is True
    assert column(Subscription, "status").default.arg == SubscriptionStatus.INACTIVE
    assert column(Subscription, "status").server_default.arg == SubscriptionStatus.INACTIVE.value
    assert column(Subscription, "uuid").unique is True
    assert column(Subscription, "uuid").index is True
    assert column(Subscription, "expires_at").index is True
    assert column(Subscription, "is_trial").nullable is False
    assert column(Subscription, "is_trial").default.arg is False
    assert str(column(Subscription, "is_trial").server_default.arg) == "false"

    trial_index = next(
        index
        for index in Subscription.__table__.indexes
        if index.name == "uq_subscriptions_one_trial_per_user"
    )
    assert trial_index.unique is True
    assert [item.name for item in trial_index.columns] == ["user_id"]
    assert (
        str(trial_index.dialect_options["postgresql"]["where"])
        == "is_trial IS TRUE"
    )
    assert (
        str(trial_index.dialect_options["sqlite"]["where"])
        == "is_trial = 1"
    )


def test_vpn_server_model_supports_multi_node_selection_and_capacity_tracking():
    assert VPNServer.__tablename__ == "vpn_servers"
    assert column(VPNServer, "name").unique is True
    assert column(VPNServer, "name").index is True
    assert column(VPNServer, "host").nullable is False
    assert str(column(VPNServer, "api_type").server_default.arg) == "3xui"
    assert column(VPNServer, "status").index is True
    assert str(column(VPNServer, "status").server_default.arg) == "active"
    assert column(VPNServer, "capacity").nullable is True
    assert column(VPNServer, "current_load").nullable is True


def test_admin_action_model_links_manual_actions_to_domain_entities():
    assert AdminAction.__tablename__ == "admin_actions"
    assert fk_targets(AdminAction, "admin_user_id") == {"users.id"}
    assert fk_targets(AdminAction, "target_user_id") == {"users.id"}
    assert fk_targets(AdminAction, "order_id") == {"orders.id"}
    assert fk_targets(AdminAction, "payment_id") == {"payments.id"}
    assert fk_targets(AdminAction, "subscription_id") == {"subscriptions.id"}
    assert column(AdminAction, "admin_user_id").index is True
    assert column(AdminAction, "target_user_id").index is True
    assert column(AdminAction, "action_type").index is True
    assert column(AdminAction, "reason").nullable is True
    assert column(AdminAction, "payload").nullable is True


def test_system_error_model_keeps_unresolved_recovery_cases_queryable():
    assert SystemErrorRecord.__tablename__ == "system_errors"
    assert column(SystemErrorRecord, "entity_type").index is True
    assert column(SystemErrorRecord, "entity_id").index is True
    assert column(SystemErrorRecord, "error_type").index is True
    assert column(SystemErrorRecord, "retry_count").default.arg == 0
    assert str(column(SystemErrorRecord, "retry_count").server_default.arg) == "0"
    assert column(SystemErrorRecord, "is_resolved").index is True
    assert column(SystemErrorRecord, "is_resolved").default.arg is False
    assert str(column(SystemErrorRecord, "is_resolved").server_default.arg) == "false"


def test_repr_methods_expose_safe_debug_identifiers_without_payload_dump():
    assert "telegram_id=777" in repr(User(id=1, telegram_id=777, username="ivan"))
    assert "code='usdt_trc20'" in repr(
        PaymentOption(
            id=2,
            code="usdt_trc20",
            payment_method=PaymentMethod.CRYPTO,
            display_name="USDT TRC20",
        )
    )
    assert "status=active" in repr(
        Subscription(
            id=3,
            user_id=1,
            status=SubscriptionStatus.ACTIVE,
            uuid="uuid-1",
        )
    )
    assert "txid='tx-1'" in repr(
        Payment(
            id=4,
            order_id=5,
            user_id=1,
            status=PaymentStatus.CONFIRMED,
            txid="tx-1",
        )
    )