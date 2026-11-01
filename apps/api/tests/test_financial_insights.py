from uuid import UUID

import pytest
from bankmate_api.infrastructure.database import get_db_session
from bankmate_api.infrastructure.models import Account, Transaction, Transfer
from bankmate_api.main import app
from bankmate_api.security.demo_identity import DEMO_USER_ONE_ID, DemoActor, get_current_demo_actor
from fastapi.testclient import TestClient
from sqlalchemy import func, select


@pytest.fixture
def insights_context(seeded_database):
    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_ONE_ID)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, seeded_database
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)


def test_recommendations_explain_synthetic_duplicate_and_monthly_cashflow(insights_context):
    client, _ = insights_context
    response = client.get("/api/v1/financial-insights/recommendations?month=2026-10")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["month"] == "2026-10"
    assert payload["generated_at"].endswith("Z") or "+00:00" in payload["generated_at"]
    by_id = {item["id"]: item for item in payload["items"]}
    duplicate = by_id["review_duplicate_charge"]
    assert duplicate["priority"] == "high"
    assert len(duplicate["source_transaction_ids"]) == 2
    assert "不代表已判定为欺诈" in duplicate["explanation"]
    assert by_id["review_monthly_cashflow"]["amount_minor"] > 0
    assert by_id["review_recurring_expenses"]["amount_minor"] > 0


def test_payday_preview_compares_scenarios_without_mutating_financial_state(insights_context):
    client, database = insights_context
    before: tuple[int, int, int] | None = None
    with database.session_factory() as session:
        before = (
            session.scalar(
                select(Account.balance_minor).where(
                    Account.id == UUID("10000000-0000-4000-8000-000000000001")
                )
            ),
            session.scalar(select(func.count()).select_from(Transfer)),
            session.scalar(select(func.count()).select_from(Transaction)),
        )

    request = {
        "recipient_name": "小林",
        "transfer_amount_minor": 20_000,
        "reserve_amount_minor": 300_000,
        "source_account_label": "Everyday account",
        "month": "2026-10",
    }
    first = client.post("/api/v1/cashflow/payday-plan-preview", json=request)
    assert first.status_code == 200, first.text
    first_plan = first.json()
    request["transfer_amount_minor"] = 100_000
    second = client.post("/api/v1/cashflow/payday-plan-preview", json=request)
    assert second.status_code == 200, second.text
    second_plan = second.json()

    assert first_plan["account_balance_minor"] == 1_250_000
    assert (
        first_plan["remaining_after_transfer_minor"] - second_plan["remaining_after_transfer_minor"]
        == 80_000
    )
    assert first_plan["monthly_income_minor"] > 0
    assert first_plan["monthly_expense_minor"] > 0
    with database.session_factory() as session:
        after = (
            session.scalar(
                select(Account.balance_minor).where(
                    Account.id == UUID("10000000-0000-4000-8000-000000000001")
                )
            ),
            session.scalar(select(func.count()).select_from(Transfer)),
            session.scalar(select(func.count()).select_from(Transaction)),
        )
    assert after == before


def test_payday_preview_rejects_invalid_amount_and_unknown_account(insights_context):
    client, _ = insights_context
    body = {
        "recipient_name": "小林",
        "transfer_amount_minor": 0,
        "reserve_amount_minor": 1000,
    }
    assert client.post("/api/v1/cashflow/payday-plan-preview", json=body).status_code == 422

    body["transfer_amount_minor"] = 100
    body["recipient_name"] = "   "
    assert client.post("/api/v1/cashflow/payday-plan-preview", json=body).status_code == 422

    body["recipient_name"] = "小林"
    body["transfer_amount_minor"] = True
    assert client.post("/api/v1/cashflow/payday-plan-preview", json=body).status_code == 422

    body["transfer_amount_minor"] = 100
    body["source_account_label"] = "不存在的账户"
    response = client.post("/api/v1/cashflow/payday-plan-preview", json=body)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "account_not_found"
