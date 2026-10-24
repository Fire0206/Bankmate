"""Birthday budget intentions must never masquerade as held funds or purchases."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from finorch_api.agent.providers import ProviderSelection
from finorch_api.agent.runtime import FakeProvider, ModelToolCall, ModelTurn
from finorch_api.api.v1.agent import get_provider_selection
from finorch_api.application.birthday_plans import list_birthday_plans
from finorch_api.infrastructure.database import get_db_session
from finorch_api.infrastructure.models import Account, AuditEvent, BirthdayPlan, Transaction
from finorch_api.main import app
from finorch_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DEMO_USER_TWO_ID,
    DemoActor,
    get_current_demo_actor,
)
from sqlalchemy import func, select
from test_agent_api import confirm, submit


@pytest.fixture
def birthday_api(seeded_database):
    actor = [DEMO_USER_ONE_ID]

    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(actor[0])
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        FakeProvider(), "fake"
    )
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client, actor, seeded_database
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)
        app.dependency_overrides.pop(get_provider_selection, None)


def _birthday() -> str:
    return (datetime.now(timezone(timedelta(hours=8))).date() + timedelta(days=12)).isoformat()


def _request() -> str:
    return f"我爱人生日是{_birthday()}，从日常账户预留1000元，生日前两天安排鲜花和蛋糕"


def test_birthday_plan_requires_date_and_account_clarification(birthday_api) -> None:
    client, _actor, database = birthday_api
    missing = submit(client, "我爱人生日想预留1000元买鲜花和蛋糕", key="birthday-missing-date")
    assert missing["status"] == "awaiting_input"
    dated = submit(
        client, f"我爱人生日是{_birthday()}，预留1000元买鲜花和蛋糕", key="birthday-missing-account"
    )
    assert dated["status"] == "awaiting_input"
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BirthdayPlan)) == 0


def test_confirmed_plan_is_reminder_without_debit_or_order(birthday_api) -> None:
    client, actor, database = birthday_api
    task = submit(client, _request(), key="birthday-plan")
    assert task["status"] == "awaiting_confirmation", task
    details = task["confirmation"]["details"]
    assert details["budget_minor"] == 100_000
    assert details["catalog_total_minor"] == 49_800
    assert details["funds_held"] is False
    assert details["order_placed"] is False
    with database.session_factory() as session:
        before_balance = session.scalar(
            select(Account.balance_minor)
            .where(Account.demo_user_id == actor[0])
            .order_by(Account.created_at)
            .limit(1)
        )
        before_transactions = session.scalar(select(func.count()).select_from(Transaction))
    actor[0] = DEMO_USER_TWO_ID
    assert confirm(client, task).status_code == 404
    assert client.get("/api/v1/birthday-plans").json()["items"] == []
    actor[0] = DEMO_USER_ONE_ID
    result = confirm(client, task)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    assert confirm(client, task).status_code == 200
    with database.session_factory() as session:
        plan = session.scalar(select(BirthdayPlan).where(BirthdayPlan.actor_id == actor[0]))
        assert plan is not None and plan.status == "scheduled"
        assert session.get(Account, plan.account_id).balance_minor == before_balance
        assert session.scalar(select(func.count()).select_from(Transaction)) == before_transactions
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "birthday.plan_scheduled")
            )
            == 1
        )
    listed = submit(client, "查询我的生日计划和到期提醒", key="birthday-list")
    assert listed["status"] == "completed", listed
    data = next(
        step["result_data"] for step in listed["steps"] if step["tool_name"] == "birthday.list"
    )
    assert data["items"][0]["funds_held"] is False
    assert data["items"][0]["order_placed"] is False
    plans = client.get("/api/v1/birthday-plans")
    assert plans.status_code == 200
    assert plans.json()["items"][0]["budget_minor"] == 100_000
    with database.session_factory() as session:
        purchase_on = session.scalar(select(BirthdayPlan.purchase_on))
        assert purchase_on is not None
        at_due = datetime.combine(
            purchase_on,
            datetime.min.time(),
            tzinfo=timezone(timedelta(hours=8)),
        )
        due = list_birthday_plans(session, actor_id=actor[0], now=at_due)
        assert due[0]["due_for_reconfirmation"] is True
        assert due[0]["order_placed"] is False


def test_birthday_plan_rejects_stale_resource_version(birthday_api) -> None:
    client, _actor, database = birthday_api
    task = submit(client, _request(), key="birthday-stale")
    assert task["status"] == "awaiting_confirmation", task
    plan_id = UUID(task["confirmation"]["resource_id"])
    with database.session_factory.begin() as session:
        session.get(BirthdayPlan, plan_id).budget_minor += 1
    result = confirm(client, task)
    assert result.status_code == 409, result.text
    with database.session_factory() as session:
        assert session.get(BirthdayPlan, plan_id).status == "pending_confirmation"


def test_birthday_plan_rejects_insufficient_funds_at_confirmation(birthday_api) -> None:
    client, _actor, database = birthday_api
    task = submit(client, _request(), key="birthday-balance")
    assert task["status"] == "awaiting_confirmation", task
    plan_id = UUID(task["confirmation"]["resource_id"])
    with database.session_factory.begin() as session:
        plan = session.get(BirthdayPlan, plan_id)
        session.get(Account, plan.account_id).balance_minor = 0
    result = confirm(client, task)
    assert result.status_code == 409, result.text
    with database.session_factory() as session:
        assert session.get(BirthdayPlan, plan_id).status == "pending_confirmation"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "birthday.plan_scheduled")
            )
            == 0
        )


def test_model_cannot_change_birthday_budget_parameters(birthday_api) -> None:
    client, _actor, database = birthday_api

    class WrongBudgetProvider(FakeProvider):
        def complete(self, messages, tools):
            del messages, tools
            return ModelTurn(
                "",
                (
                    ModelToolCall(
                        "wrong-budget",
                        "birthday.plan",
                        json.dumps(
                            {
                                "birthday_on": _birthday(),
                                "budget_minor": 99_900,
                                "account_label": "Everyday account",
                            }
                        ),
                    ),
                ),
            )

    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        WrongBudgetProvider(), "fake"
    )
    task = submit(client, _request(), key="birthday-wrong-model-budget")
    assert task["status"] == "failed"
    assert task["error_code"] == "birthday_parameter_mismatch"
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BirthdayPlan)) == 0
