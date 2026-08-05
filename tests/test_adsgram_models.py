from __future__ import annotations

import app.database.models as models_package
from app.database.models import AdsGramConversion, User


def column(model, name: str):
    return model.__table__.c[name]


def fk_targets(model, name: str) -> set[str]:
    return {fk.target_fullname for fk in column(model, name).foreign_keys}


def test_models_package_exports_adsgram_conversion():
    assert models_package.AdsGramConversion is AdsGramConversion


def test_user_model_keeps_first_touch_adsgram_attribution():
    assert column(User, "adsgram_campaign_id").nullable is True
    assert column(User, "adsgram_campaign_id").index is True
    assert column(User, "adsgram_attributed_at").nullable is True


def test_adsgram_conversion_model_is_retryable_and_idempotent():
    assert AdsGramConversion.__tablename__ == "adsgram_conversions"
    assert fk_targets(AdsGramConversion, "user_id") == {"users.id"}
    assert fk_targets(AdsGramConversion, "order_id") == {"orders.id"}

    assert column(AdsGramConversion, "user_id").index is True
    assert column(AdsGramConversion, "order_id").index is True
    assert column(AdsGramConversion, "campaign_id").index is True

    assert column(AdsGramConversion, "idempotency_key").unique is True
    assert column(AdsGramConversion, "idempotency_key").index is True

    assert column(AdsGramConversion, "status").default.arg == "pending"
    assert (
        str(column(AdsGramConversion, "status").server_default.arg)
        == "pending"
    )

    assert column(AdsGramConversion, "attempt_count").default.arg == 0
    assert (
        str(column(AdsGramConversion, "attempt_count").server_default.arg)
        == "0"
    )

    assert column(AdsGramConversion, "claimed_at").index is True
    assert column(AdsGramConversion, "sent_at").index is True

    composite_index = next(
        index
        for index in AdsGramConversion.__table__.indexes
        if index.name
        == "ix_adsgram_conversions_status_next_attempt_at"
    )
    assert [item.name for item in composite_index.columns] == [
        "status",
        "next_attempt_at",
    ]