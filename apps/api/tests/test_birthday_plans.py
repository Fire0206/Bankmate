"""Birthday budgets reserve synthetic funds and require a fresh order confirmation."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from bankmate_api.agent.providers import ProviderSelection
from bankmate_api.agent.runtime import FakeProvider, ModelToolCall, ModelTurn
from bankmate_api.api.v1.agent import get_provider_selection
from bankmate_api.application.birthday_plans import dispatch_due_birthday_orders
from bankmate_api.application.funds import available_balance_minor
from bankmate_api.config import get_settings
from bankmate_api.infrastructure.database import get_db_session
from bankmate_api.infrastructure.models import (
    Account,
    AuditEvent,
    BirthdayOrder,
    BirthdayPlan,
    FundsReservation,
    Transaction,
)
from bankmate_api.main import app
from bankmate_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DEMO_USER_TWO_ID,
    DemoActor,
    get_current_demo_actor,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from test_agent_api import confirm, submit

BUSINESS_TZ = timezone(timedelta(hours=8))


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
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, actor, seeded_database
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)
        app.dependency_overrides.pop(get_provider_selection, None)


def _birthday() -> str:
    return (datetime.now(BUSINESS_TZ).date() + timedelta(days=12)).isoformat()


def _request() -> str:
    return f"我爱人生日是{_birthday()}，从日常账户预留1000元，生日前两天安排鲜花和蛋糕"


def _make_plan(client: TestClient, actor, database, *, key: str = "birthday-plan") -> dict:
    task = submit(client, _request(), key=key)
    assert task["status"] == "awaiting_confirmation", task
    assert task["confirmation"]["tool_name"] == "birthday.plan"
    assert "确认后会预留预算" in task["message"]
    assert "定时转账" not in task["message"]
    proposal = task["steps"][-1]["result_data"]
    assert proposal["funds_held"] is False
    assert proposal["order_placed"] is False
    with database.session_factory() as session:
        account = session.scalar(
            select(Account).where(
                Account.demo_user_id == actor[0], Account.label == "Everyday account"
            )
        )
        assert account is not None
        balance_before = account.balance_minor
        assert session.scalar(select(func.count()).select_from(FundsReservation)) == 0
        assert session.scalar(select(func.count()).select_from(BirthdayOrder)) == 0
    confirmed = confirm(client, task)
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert confirm(client, task).status_code == 200
    assert result["status"] == "completed", result
    with database.session_factory() as session:
        plan = session.scalar(select(BirthdayPlan).where(BirthdayPlan.actor_id == actor[0]))
        assert plan is not None and plan.status == "scheduled"
        reservation = session.scalar(
            select(FundsReservation).where(FundsReservation.birthday_plan_id == plan.id)
        )
        order = session.scalar(select(BirthdayOrder).where(BirthdayOrder.plan_id == plan.id))
        account = session.get(Account, plan.account_id)
        assert reservation is not None and reservation.status == "held"
        assert reservation.held_minor == plan.budget_minor == 100_000
        assert order is not None and order.status == "scheduled"
        assert order.total_amount_minor == 49_800
        assert account is not None and account.balance_minor == balance_before
        assert available_balance_minor(session, account=account) == balance_before - 100_000
    return result


def _dispatch_due(database, plan_id: UUID) -> None:
    with database.session_factory() as session:
        plan = session.get(BirthdayPlan, plan_id)
        assert plan is not None
        due_time = datetime.combine(plan.purchase_on, datetime.min.time(), tzinfo=BUSINESS_TZ)
        assert dispatch_due_birthday_orders(session, now=due_time) == 1
    with database.session_factory() as session:
        plan = session.get(BirthdayPlan, plan_id)
        assert plan is not None
        due_time = datetime.combine(plan.purchase_on, datetime.min.time(), tzinfo=BUSINESS_TZ)
        assert dispatch_due_birthday_orders(session, now=due_time + timedelta(minutes=1)) == 0


def test_birthday_plan_holds_funds_without_debit_and_is_idempotent(birthday_api) -> None:
    client, actor, database = birthday_api
    _make_plan(client, actor, database)
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Transaction)) == 31
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "birthday.funds_reserved")
            )
            == 1
        )
    listed = client.get("/api/v1/birthday-plans")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["funds_held"] is True
    assert item["held_minor"] == 100_000
    assert item["order_placed"] is False
    assert item["order_status"] == "scheduled"


def test_birthday_date_is_clarified_but_default_account_is_shown_for_confirmation(
    birthday_api,
) -> None:
    client, _actor, database = birthday_api
    missing_date = submit(client, "我爱人生日想预留1000元买鲜花和蛋糕", key="birthday-missing-date")
    assert missing_date["status"] == "awaiting_input"
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BirthdayPlan)) == 0

    task = submit(
        client,
        "我爱人11月20日生日，预留1000元买鲜花和蛋糕",
        key="birthday-default-account",
    )
    assert task["status"] == "awaiting_confirmation", task
    assert task["confirmation"]["details"]["account_label"] == "Everyday account"
    assert task["confirmation"]["details"]["funds_held"] is False


def test_birthday_plan_uses_user_grounded_account_and_card(birthday_api, monkeypatch) -> None:
    client, actor, database = birthday_api

    class LocalizedToolProvider(FakeProvider):
        def complete(self, messages, tools):
            tool_count = sum(item.get("role") == "tool" for item in messages)
            calls = (
                ("transfer__accounts", "{}"),
                ("card__catalog", "{}"),
                (
                    "birthday__plan",
                    json.dumps(
                        {
                            "birthday_on": "2027-01-01",
                            "budget_minor": 500_000,
                            "account_label": "日常账户",
                            "card_suffix": "9999",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            name, arguments = calls[tool_count]
            return ModelTurn(
                content=None,
                tool_calls=(ModelToolCall(f"call-{tool_count}", name, arguments),),
            )

        def complete_required_tool(self, messages, tools, tool_name):
            del messages, tools
            if tool_name == "transfer.accounts":
                return ModelTurn(
                    None, (ModelToolCall("required-accounts", "transfer__accounts", "{}"),)
                )
            if tool_name == "card.catalog":
                return ModelTurn(None, (ModelToolCall("required-catalog", "card__catalog", "{}"),))
            if tool_name == "birthday.plan":
                arguments = json.dumps(
                    {
                        "birthday_on": "2027-01-01",
                        "budget_minor": 500_000,
                        "account_label": "日常账户",
                        "card_suffix": "9999",
                    },
                    ensure_ascii=False,
                )
                return ModelTurn(
                    None,
                    (ModelToolCall("required-plan", "birthday__plan", arguments),),
                )
            raise AssertionError(f"Unexpected required tool: {tool_name}")

    monkeypatch.setitem(
        app.dependency_overrides,
        get_provider_selection,
        lambda: ProviderSelection(LocalizedToolProvider(), "fake"),
    )
    with TestClient(app, raise_server_exceptions=True) as strict_client:
        task = submit(strict_client, _request(), key="birthday-grounded-selection")
    assert task["status"] == "awaiting_confirmation", task
    details = task["confirmation"]["details"]
    assert details["account_label"] == "Everyday account"
    assert details["card_suffix"] != "9999"
    assert details["budget_minor"] == 100_000
    assert details["birthday_on"] == _birthday()
    with database.session_factory() as session:
        account = session.scalar(
            select(Account).where(
                Account.demo_user_id == actor[0], Account.label == "Everyday account"
            )
        )
        assert account is not None
        assert session.scalar(select(func.count()).select_from(FundsReservation)) == 0


def test_other_user_cannot_read_or_confirm_owned_birthday_plan(birthday_api) -> None:
    client, actor, database = birthday_api
    task = submit(client, _request(), key="birthday-owner")
    assert task["status"] == "awaiting_confirmation"
    actor[0] = DEMO_USER_TWO_ID
    assert confirm(client, task).status_code == 404
    assert client.get("/api/v1/birthday-plans").json()["items"] == []
    actor[0] = DEMO_USER_ONE_ID
    confirmed = confirm(client, task)
    assert confirmed.status_code == 200, confirmed.text
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(FundsReservation)) == 1


def test_birthday_plan_confirmation_rechecks_available_balance(birthday_api) -> None:
    client, actor, database = birthday_api
    task = submit(client, _request(), key="birthday-balance")
    assert task["status"] == "awaiting_confirmation"
    plan_id = UUID(task["confirmation"]["resource_id"])
    with database.session_factory.begin() as session:
        plan = session.get(BirthdayPlan, plan_id)
        assert plan is not None
        session.get(Account, plan.account_id).balance_minor = 0
    result = confirm(client, task)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "insufficient_funds"
    with database.session_factory() as session:
        assert session.get(BirthdayPlan, plan_id).status == "cancelled"
        assert session.scalar(select(func.count()).select_from(FundsReservation)) == 0
        assert session.scalar(select(func.count()).select_from(BirthdayOrder)) == 0


def test_concurrent_birthday_reservations_cannot_overcommit_the_account(birthday_api) -> None:
    client, actor, database = birthday_api
    with database.session_factory.begin() as session:
        account = session.scalar(
            select(Account).where(
                Account.demo_user_id == actor[0], Account.label == "Everyday account"
            )
        )
        assert account is not None
        account.balance_minor = 150_000

    tasks = [submit(client, _request(), key=f"birthday-concurrent-{index}") for index in range(2)]
    assert all(task["status"] == "awaiting_confirmation" for task in tasks)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda task: confirm(client, task), tasks))

    assert sorted(response.status_code for response in responses) == [200, 409]
    failed = next(response for response in responses if response.status_code == 409)
    assert failed.json()["error"]["code"] == "insufficient_funds"
    with database.session_factory() as session:
        plans = list(session.scalars(select(BirthdayPlan).order_by(BirthdayPlan.created_at)))
        reservations = list(session.scalars(select(FundsReservation)))
        account = session.scalar(
            select(Account).where(
                Account.demo_user_id == actor[0], Account.label == "Everyday account"
            )
        )
        assert len(plans) == 2
        assert sorted(plan.status for plan in plans) == ["cancelled", "scheduled"]
        assert len(reservations) == 1 and reservations[0].held_minor == 100_000
        assert account is not None and available_balance_minor(session, account=account) == 50_000


def test_held_birthday_budget_is_not_available_for_transfer(birthday_api) -> None:
    client, actor, database = birthday_api
    _make_plan(client, actor, database)
    with database.session_factory.begin() as session:
        account = session.scalar(
            select(Account).where(
                Account.demo_user_id == actor[0], Account.label == "Everyday account"
            )
        )
        assert account is not None
        account.balance_minor = 150_000

    transfer = submit(client, "给小林转600元", key="birthday-reserved-transfer")
    assert transfer["status"] == "failed"
    assert transfer["error_code"] == "insufficient_funds"
    assert not any(
        step["tool_name"] == "transfer.create" and step["status"] == "succeeded"
        for step in transfer["steps"]
    )
    with database.session_factory() as session:
        account = session.scalar(
            select(Account).where(
                Account.demo_user_id == actor[0], Account.label == "Everyday account"
            )
        )
        assert account is not None and account.balance_minor == 150_000
        assert available_balance_minor(session, account=account) == 50_000
        assert session.scalar(select(func.count()).select_from(Transaction)) == 31
        assert session.scalar(select(func.count()).select_from(FundsReservation)) == 1


def test_cancelling_initial_birthday_confirmation_leaves_no_orphan_plan(birthday_api) -> None:
    client, _actor, database = birthday_api
    task = submit(client, _request(), key="birthday-cancel-pending-confirmation")
    assert task["status"] == "awaiting_confirmation"
    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/cancel",
        headers={"Idempotency-Key": "birthday-cancel-pending-confirmation"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    with database.session_factory() as session:
        plan = session.scalar(select(BirthdayPlan))
        assert plan is not None and plan.status == "cancelled"
        assert session.scalar(select(func.count()).select_from(FundsReservation)) == 0


def test_reading_saved_birthday_gift_budget_uses_list_tool_without_proposing_a_write(
    birthday_api,
) -> None:
    client, _actor, database = birthday_api
    task = submit(
        client,
        "查看已保存的生日赠礼预算和订单状态。",
        key="birthday-read-saved-gift-budget",
    )

    assert task["status"] == "completed", (
        task["error_code"],
        [(step["tool_name"], step["status"]) for step in task["steps"]],
    )
    assert any(step["tool_name"] == "birthday.list" for step in task["steps"])
    assert task["confirmation"] is None
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BirthdayPlan)) == 0
        assert session.scalar(select(func.count()).select_from(BirthdayOrder)) == 0
        assert session.scalar(select(func.count()).select_from(Transaction)) == 31


def test_due_scheduler_and_fresh_order_confirmation_create_one_real_simulated_transaction(
    birthday_api,
    monkeypatch,
) -> None:
    client, actor, database = birthday_api
    _make_plan(client, actor, database)
    with database.session_factory() as session:
        plan = session.scalar(select(BirthdayPlan).where(BirthdayPlan.actor_id == actor[0]))
        assert plan is not None
        plan_id = plan.id
    _dispatch_due(database, plan_id)
    with database.session_factory() as session:
        plan = session.get(BirthdayPlan, plan_id)
        assert plan is not None
        due_time = datetime.combine(plan.purchase_on, datetime.min.time(), tzinfo=BUSINESS_TZ)
    monkeypatch.setattr(get_settings(), "demo_now", due_time)

    due_task = submit(client, "请确认购买已到期的生日礼品订单", key="birthday-order-purchase")
    assert due_task["status"] == "awaiting_confirmation", due_task
    assert due_task["confirmation"]["tool_name"] == "birthday.order"
    assert due_task["confirmation"]["resource_type"] == "birthday_order"
    assert "模拟订单" in due_task["message"] and "确认后才会扣款" in due_task["message"]
    assert due_task["confirmation"]["details"]["amount_minor"] == 49_800
    paid = confirm(client, due_task)
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "completed"
    assert "已支付" in paid.json()["message"]
    assert "尚未扣款" not in paid.json()["message"]
    assert confirm(client, due_task).json()["status"] == "completed"

    with database.session_factory() as session:
        plan = session.get(BirthdayPlan, plan_id)
        assert plan is not None and plan.status == "completed"
        order = session.scalar(select(BirthdayOrder).where(BirthdayOrder.plan_id == plan_id))
        reservation = session.scalar(
            select(FundsReservation).where(FundsReservation.birthday_plan_id == plan_id)
        )
        assert order is not None and order.status == "paid" and order.transaction_id is not None
        assert reservation is not None and reservation.status == "consumed"
        assert reservation.held_minor == 0
        assert reservation.consumed_minor == 49_800
        assert reservation.released_minor == 50_200
        transaction = session.get(Transaction, order.transaction_id)
        assert transaction is not None
        assert transaction.amount_minor == order.total_amount_minor == 49_800
        assert transaction.synthetic_ref == f"birthday-order:{order.id}"
        assert session.scalar(select(func.count()).select_from(Transaction)) == 32
        account = session.get(Account, order.account_id)
        assert account is not None
        assert account.balance_minor == 1_250_000 - 49_800
        event_types = set(
            session.scalars(
                select(AuditEvent.event_type).where(
                    AuditEvent.resource_id.in_([order.id, reservation.id])
                )
            )
        )
        assert {
            "birthday.order_paid",
            "birthday.funds_consumed",
            "birthday.funds_released",
        } <= event_types
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "birthday.order_due")
            )
            == 1
        )

    # Reset must delete the order before its restrictive payment transaction FK.
    from bankmate_api.reset import reset_demo_data

    with database.session_factory.begin() as session:
        reset_demo_data(session)
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BirthdayOrder)) == 0
        assert session.scalar(select(func.count()).select_from(Transaction)) == 31


def test_budget_update_and_cancel_require_confirmation_and_release_funds(birthday_api) -> None:
    client, actor, database = birthday_api
    _make_plan(client, actor, database)
    update_task = submit(client, "把我的生日预算调整到1200元", key="birthday-budget-update")
    assert update_task["status"] == "awaiting_confirmation", update_task
    assert update_task["confirmation"]["tool_name"] == "birthday.budget_update"
    assert update_task["confirmation"]["details"]["proposed_budget_minor"] == 120_000
    updated = confirm(client, update_task)
    assert updated.status_code == 200, updated.text
    with database.session_factory() as session:
        plan = session.scalar(select(BirthdayPlan).where(BirthdayPlan.actor_id == actor[0]))
        reservation = session.scalar(select(FundsReservation))
        assert plan is not None and plan.budget_minor == 120_000
        assert reservation is not None and reservation.held_minor == 120_000

    cancel_task = submit(client, "取消我的生日计划", key="birthday-plan-cancel")
    assert cancel_task["status"] == "awaiting_confirmation", cancel_task
    assert cancel_task["confirmation"]["tool_name"] == "birthday.cancel"
    cancelled = confirm(client, cancel_task)
    assert cancelled.status_code == 200, cancelled.text
    with database.session_factory() as session:
        plan = session.scalar(select(BirthdayPlan).where(BirthdayPlan.actor_id == actor[0]))
        reservation = session.scalar(select(FundsReservation))
        order = session.scalar(select(BirthdayOrder))
        assert plan is not None and plan.status == "cancelled"
        assert reservation is not None and reservation.status == "released"
        assert reservation.held_minor == 0 and reservation.released_minor == 120_000
        assert order is not None and order.status == "cancelled"
        assert available_balance_minor(session, account=session.get(Account, plan.account_id)) == (
            session.get(Account, plan.account_id).balance_minor
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "birthday.plan_cancelled")
            )
            == 1
        )


def test_failed_order_insert_rolls_back_debit_reservation_and_status(
    birthday_api, monkeypatch
) -> None:
    client, actor, database = birthday_api
    _make_plan(client, actor, database)
    with database.session_factory() as session:
        plan = session.scalar(select(BirthdayPlan).where(BirthdayPlan.actor_id == actor[0]))
        assert plan is not None
        plan_id = plan.id
    _dispatch_due(database, plan_id)
    with database.session_factory() as session:
        plan = session.get(BirthdayPlan, plan_id)
        assert plan is not None
        due_time = datetime.combine(plan.purchase_on, datetime.min.time(), tzinfo=BUSINESS_TZ)
    monkeypatch.setattr(get_settings(), "demo_now", due_time)
    due_task = submit(client, "确认购买已到期的生日礼品订单", key="birthday-order-fault")
    assert due_task["status"] == "awaiting_confirmation", due_task
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER fail_birthday_transaction BEFORE INSERT ON transactions "
                "WHEN NEW.synthetic_ref LIKE 'birthday-order:%' "
                "BEGIN SELECT RAISE(ABORT, 'injected test failure'); END"
            )
        )
    result = confirm(client, due_task)
    assert result.status_code == 500
    with database.session_factory() as session:
        plan = session.get(BirthdayPlan, plan_id)
        order = session.scalar(select(BirthdayOrder).where(BirthdayOrder.plan_id == plan_id))
        reservation = session.scalar(
            select(FundsReservation).where(FundsReservation.birthday_plan_id == plan_id)
        )
        account = session.get(Account, plan.account_id)
        assert plan is not None and plan.status == "scheduled"
        assert order is not None and order.status == "awaiting_confirmation"
        assert reservation is not None and reservation.status == "held"
        assert reservation.held_minor == 100_000 and reservation.consumed_minor == 0
        assert account is not None and account.balance_minor == 1_250_000
        assert session.scalar(select(func.count()).select_from(Transaction)) == 31


def test_cancelled_plan_is_not_dispatched_due_again(birthday_api) -> None:
    client, actor, database = birthday_api
    _make_plan(client, actor, database)
    cancel_task = submit(client, "取消我的生日计划", key="birthday-cancel-before-due")
    assert cancel_task["status"] == "awaiting_confirmation"
    assert confirm(client, cancel_task).status_code == 200
    with database.session_factory() as session:
        plan = session.scalar(select(BirthdayPlan).where(BirthdayPlan.actor_id == actor[0]))
        assert plan is not None
        due_time = datetime.combine(plan.purchase_on, datetime.min.time(), tzinfo=BUSINESS_TZ)
        assert dispatch_due_birthday_orders(session, now=due_time) == 0
        order = session.scalar(select(BirthdayOrder).where(BirthdayOrder.plan_id == plan.id))
        assert order is not None and order.status == "cancelled"
