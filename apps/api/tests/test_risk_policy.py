from datetime import UTC, datetime

import pytest

from bankmate_api.security.risk_policy import business_day_bounds, decide_risk


def test_read_is_low_risk_but_write_requires_confirmation():
    assert decide_risk(operation="read").confirmation_method == "none"
    assert decide_risk(operation="write").confirmation_method == "explicit"


@pytest.mark.parametrize(
    ("amount", "previous", "level"),
    [
        (100_000, 0, "yellow"),
        (1, 100_000, "red"),
        (60_000, 40_000, "yellow"),
        (60_001, 40_000, "red"),
        (100_001, 0, "red"),
    ],
)
def test_daily_transfer_threshold(amount, previous, level):
    decision = decide_risk(operation="transfer", amount_minor=amount, daily_executed_minor=previous)
    assert decision.level == level
    assert decision.confirmation_method == ("demo_otp" if level == "red" else "explicit")


def test_business_day_is_utc_plus_eight_and_boundary_is_half_open():
    start, end = business_day_bounds(datetime(2026, 10, 22, 16, tzinfo=UTC))
    assert start == datetime(2026, 10, 22, 16, tzinfo=UTC)
    assert end == datetime(2026, 10, 23, 16, tzinfo=UTC)
    with pytest.raises(ValueError):
        business_day_bounds(datetime(2026, 10, 22))


@pytest.mark.parametrize("risk", [4, 5])
def test_high_risk_product_requires_strong_verification(risk):
    assert decide_risk(operation="investment_buy", product_risk=risk).level == "red"


def test_sensitive_operation_and_signal_escalate():
    assert decide_risk(operation="sensitive_card").confirmation_method == "demo_otp"
    assert decide_risk(operation="write", high_risk_signal=True).level == "red"


@pytest.mark.parametrize("amount", [True, 1.5, -1, 0])
def test_invalid_transfer_amount_fails_closed(amount):
    with pytest.raises(ValueError):
        decide_risk(operation="transfer", amount_minor=amount)


def test_unknown_product_risk_and_currency_fail_closed():
    with pytest.raises(ValueError):
        decide_risk(operation="investment_buy")
    with pytest.raises(ValueError):
        decide_risk(operation="transfer", amount_minor=1, currency="USD")
