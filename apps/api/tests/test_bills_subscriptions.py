from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from bankmate_api.agent.providers import ProviderSelection
from bankmate_api.agent.runtime import FakeProvider
from bankmate_api.api.v1.agent import get_provider_selection
from bankmate_api.application import agent as agent_application
from bankmate_api.infrastructure.database import get_db_session
from bankmate_api.infrastructure.models import (
    AgentTask,
    AuditEvent,
    ConfirmationChallenge,
    Subscription,
    ToolExecution,
    Transaction,
)
from bankmate_api.main import app
from bankmate_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DEMO_USER_TWO_ID,
    DemoActor,
    get_current_demo_actor,
)

CONVERSATION_ID = "30000000-0000-4000-8000-000000000001"


@pytest.fixture
def bill_agent_context(seeded_database):
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


def submit(client: TestClient, text: str, key: str) -> dict:
    response = client.post(
        "/api/v1/agent/tasks",
        json={"request_text": text, "conversation_id": CONVERSATION_ID},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client: TestClient, task: dict):
    challenge = task["confirmation"]
    return client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json={
            "challenge_id": challenge["id"],
            "parameters_hash": challenge["parameters_hash"],
        },
        headers={"Idempotency-Key": challenge["idempotency_key"]},
    )


def tool_result(task: dict, name: str) -> dict:
    return next(step["result_data"] for step in task["steps"] if step["tool_name"] == name)


def test_monthly_summary_and_category_totals_are_calculated_from_owned_rows(bill_agent_context):
    client, _actor, database = bill_agent_context
    summary_response = client.get("/api/v1/bills/summary?month=2026-10")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["income_minor"] == 650_000
    assert summary["expense_minor"] == 2_003_500
    assert summary["net_minor"] == -1_353_500
    assert summary["selected_category_expense_minor"] is None
    assert summary["anomalies"][0]["merchant"] == "星河数码"

    category_response = client.get(
        "/api/v1/bills/summary", params={"month": "2026-10", "category": "餐饮"}
    )
    assert category_response.status_code == 200
    assert category_response.json()["selected_category_expense_minor"] == 11_440

    with database.session_factory() as session:
        owned_transactions = session.scalar(
            select(func.count())
            .select_from(Transaction)
            .join(Transaction.account)
            .where(Transaction.account.has(demo_user_id=DEMO_USER_ONE_ID))
        )
        assert owned_transactions > 0


def test_annual_report_aggregates_owned_transactions_and_agent_reads_it(bill_agent_context):
    client, actor, database = bill_agent_context
    response = client.get("/api/v1/bills/annual", params={"year": 2026})
    assert response.status_code == 200
    annual = response.json()
    assert len(annual["monthly_totals"]) == 12
    assert annual["monthly_totals"][9]["month"] == "2026-10"
    assert annual["monthly_totals"][9]["expense_minor"] == 2_003_500
    assert annual["income_minor"] == sum(
        month["income_minor"] for month in annual["monthly_totals"]
    )
    assert annual["expense_minor"] == sum(
        month["expense_minor"] for month in annual["monthly_totals"]
    )
    assert annual["expense_minor"] == sum(item["amount_minor"] for item in annual["categories"])
    assert annual["top_expense_category"] == annual["categories"][0]["category"]
    assert annual["anomalies"]
    task = submit(client, "查看 2026 年度账单", "annual-bill-agent")
    assert task["status"] == "completed"
    assert tool_result(task, "bill.annual_report")["expense_minor"] == annual["expense_minor"]

    actor[0] = DEMO_USER_TWO_ID
    other = client.get("/api/v1/bills/annual", params={"year": 2026})
    assert other.status_code == 200
    assert other.json()["expense_minor"] != annual["expense_minor"]
    assert client.get("/api/v1/bills/annual?year=1999").status_code == 422


def test_fake_agent_completes_annual_report_and_renewal_reminders_together(bill_agent_context):
    client, _actor, _database = bill_agent_context
    annual = client.get("/api/v1/bills/annual", params={"year": 2026}).json()

    task = submit(
        client,
        "查看2026年度账单，并列出即将到期的续费提醒",
        "annual-bill-and-reminders",
    )

    assert task["status"] == "completed", [
        (step["tool_name"], step["status"], step["error_code"]) for step in task["steps"]
    ]
    successful_tools = [
        step["tool_name"]
        for step in task["steps"]
        if step["tool_name"] and step["status"] == "succeeded"
    ]
    assert successful_tools.count("bill.annual_report") == 1
    assert successful_tools.count("subscription.reminders") == 1
    assert tool_result(task, "bill.annual_report")["expense_minor"] == annual["expense_minor"]
    assert len(tool_result(task, "subscription.reminders")["items"]) == 3


def test_transaction_filters_and_demo_actor_scope(bill_agent_context):
    client, actor, _database = bill_agent_context
    response = client.get(
        "/api/v1/transactions",
        params={"month": "2026-10", "category": "餐饮", "limit": 10},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert {item["merchant"] for item in response.json()["items"]} == {
        "小满面馆",
        "邻里超市",
        "咖啡工坊",
    }
    merchant_response = client.get(
        "/api/v1/transactions",
        params={"month": "2026-10", "merchant": "面馆", "limit": 10},
    )
    assert merchant_response.status_code == 200
    assert merchant_response.json()["total"] == 1
    assert merchant_response.json()["items"][0]["merchant"] == "小满面馆"

    actor[0] = DEMO_USER_TWO_ID
    other_user = client.get("/api/v1/transactions?month=2026-10")
    assert other_user.status_code == 200
    assert other_user.json()["total"] == 1
    assert other_user.json()["items"][0]["merchant"] == "海边食堂"
    assert client.get("/api/v1/subscriptions").json()["items"] == []
    unauthorized_task = submit(client, "取消腾讯视频会员自动续费", "foreign-subscription-write")
    assert unauthorized_task["status"] == "failed"
    assert unauthorized_task["error_code"] == "subscription_not_found"
    assert unauthorized_task["confirmation"] is None
    with _database.session_factory() as session:
        owner_subscription = session.scalar(
            select(Subscription).where(Subscription.merchant == "腾讯视频会员")
        )
        assert owner_subscription is not None and owner_subscription.status == "active"


def test_seed_detects_monthly_subscriptions_from_recurring_expenses(bill_agent_context):
    client, _actor, database = bill_agent_context
    response = client.get("/api/v1/subscriptions")
    assert response.status_code == 200
    payload = response.json()
    assert payload["monthly_total_minor"] == 5_600
    assert {item["merchant"] for item in payload["items"]} == {
        "腾讯视频会员",
        "网易云音乐会员",
        "云盘会员",
    }
    assert all(item["detected_charge_count"] == 6 for item in payload["items"])
    assert all(item["status"] == "active" for item in payload["items"])
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Subscription)) == 3


@pytest.mark.parametrize(
    ("request_text", "tool_name", "expected"),
    (
        ("我这个月花了多少钱", "bill.monthly_summary", 2_003_500),
        ("餐饮支出多少", "bill.monthly_summary", 11_440),
    ),
)
def test_fake_agent_bill_requests_return_real_database_totals(
    bill_agent_context, request_text, tool_name, expected
):
    client, _actor, _database = bill_agent_context
    task = submit(client, request_text, f"bill-query-{tool_name}-{expected}")
    assert task["status"] == "completed"
    result = tool_result(task, tool_name)
    if expected == 11_440:
        assert result["selected_category_expense_minor"] == expected
    else:
        assert result["expense_minor"] == expected


def test_fake_agent_detects_anomaly_and_lists_subscriptions(bill_agent_context):
    client, _actor, _database = bill_agent_context
    anomaly_task = submit(client, "最近有没有异常消费", "bill-anomaly-query")
    anomalies = tool_result(anomaly_task, "bill.anomalies")
    assert {item["merchant"] for item in anomalies["items"]} == {
        "星河数码",
        "腾讯视频会员",
    }
    duplicate_charges = [item for item in anomalies["items"] if item["merchant"] == "腾讯视频会员"]
    assert len(duplicate_charges) == 2
    assert all("重复扣费提示" in item["anomaly_reason"] for item in duplicate_charges)
    assert all(item["source_card_suffix"] == "1042" for item in duplicate_charges)
    assert all("不代表欺诈" in item["anomaly_reason"] for item in duplicate_charges)

    subscription_task = submit(client, "我有哪些自动扣费", "subscription-list-query")
    subscriptions = tool_result(subscription_task, "subscription.list")
    assert len(subscriptions["items"]) == 3
    assert subscriptions["monthly_total_minor"] == 5_600


def test_fake_agent_queries_transactions_by_merchant(bill_agent_context):
    client, _actor, _database = bill_agent_context
    task = submit(client, "小满面馆的交易明细", "bill-merchant-query")

    assert task["status"] == "completed"
    result = tool_result(task, "bill.transactions")
    assert result["total"] == 1
    assert [item["merchant"] for item in result["items"]] == ["小满面馆"]


def test_subscription_cancel_requires_confirmation_and_is_idempotent(bill_agent_context):
    client, _actor, database = bill_agent_context
    task = submit(client, "取消这个视频会员的自动续费", "subscription-cancel")
    assert task["status"] == "awaiting_confirmation"
    assert task["confirmation"]["resource_type"] == "subscription"
    assert task["confirmation"]["resource_label"] == "腾讯视频会员"
    assert task["confirmation"]["current_status"] == "active"
    assert task["confirmation"]["target_status"] == "cancelled"
    with database.session_factory() as session:
        subscription = session.scalar(
            select(Subscription).where(Subscription.merchant == "腾讯视频会员")
        )
        assert subscription is not None and subscription.status == "active"

    first = confirm(client, task)
    second = confirm(client, task)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "completed"
    assert tool_result(first.json(), "subscription.cancel")["subscription"]["status"] == "cancelled"
    with database.session_factory() as session:
        subscription = session.scalar(
            select(Subscription).where(Subscription.merchant == "腾讯视频会员")
        )
        assert subscription is not None and subscription.status == "cancelled"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.resource_id == subscription.id,
                    AuditEvent.event_type == "subscription.status_changed",
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ConfirmationChallenge)
                .where(ConfirmationChallenge.status == "consumed")
            )
            == 1
        )


def test_subscription_pause_resume_and_illegal_transition(bill_agent_context):
    client, _actor, database = bill_agent_context
    pause_task = submit(client, "暂停云盘会员自动扣费", "subscription-pause")
    assert pause_task["status"] == "awaiting_confirmation"
    assert confirm(client, pause_task).json()["status"] == "completed"

    resume_task = submit(
        client,
        "把云盘会员从暂停状态恢复成正常续费。",
        "subscription-resume",
    )
    assert resume_task["status"] == "awaiting_confirmation"
    assert resume_task["steps"][-1]["tool_name"] == "subscription.resume"
    resumed = confirm(client, resume_task)
    assert resumed.json()["status"] == "completed"
    assert all(step["tool_name"] != "subscription.pause" for step in resumed.json()["steps"])
    refreshed = client.get(f"/api/v1/agent/tasks/{resume_task['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "completed"

    with database.session_factory() as session:
        subscription = session.scalar(
            select(Subscription).where(Subscription.merchant == "云盘会员")
        )
        assert subscription is not None and subscription.status == "active"

    cancel_task = submit(client, "取消云盘会员自动续费", "subscription-cancel-cloud")
    assert confirm(client, cancel_task).json()["status"] == "completed"
    invalid_task = submit(client, "暂停云盘会员", "subscription-pause-cancelled")
    assert invalid_task["status"] == "failed"
    assert invalid_task["error_code"] == "invalid_subscription_transition"


def test_subscription_confirmation_rejects_stale_version(bill_agent_context):
    client, _actor, database = bill_agent_context
    task = submit(client, "暂停云盘会员", "subscription-version-conflict")
    subscription_id = UUID(task["confirmation"]["resource_id"])
    with database.session_factory.begin() as session:
        session.execute(
            update(Subscription)
            .where(Subscription.id == subscription_id)
            .values(version=Subscription.version + 1)
        )
    response = confirm(client, task)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "subscription_version_conflict"
    with database.session_factory() as session:
        subscription = session.get(Subscription, subscription_id)
        challenge = session.get(ConfirmationChallenge, UUID(task["confirmation"]["id"]))
        assert subscription is not None and subscription.status == "active"
        assert challenge is not None and challenge.status == "invalidated"


def test_expired_subscription_confirmation_is_settled_on_task_read(bill_agent_context):
    client, _actor, database = bill_agent_context
    task = submit(client, "暂停云盘会员", "subscription-expired-confirmation")
    challenge_id = UUID(task["confirmation"]["id"])
    subscription_id = UUID(task["confirmation"]["subscription_id"])
    with database.session_factory.begin() as session:
        session.execute(
            update(ConfirmationChallenge)
            .where(ConfirmationChallenge.id == challenge_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    response = client.get(f"/api/v1/agent/tasks/{task['id']}")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "confirmation_expired"
    assert response.json()["confirmation"] is None
    with database.session_factory() as session:
        subscription = session.get(Subscription, subscription_id)
        challenge = session.get(ConfirmationChallenge, challenge_id)
        expiry_audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.resource_id == subscription_id,
                    AuditEvent.event_type == "subscription.confirmation_expired",
                )
            )
        )
        assert subscription is not None and subscription.status == "active"
        assert challenge is not None and challenge.status == "expired"
        assert len(expiry_audits) == 1


def test_subscription_change_rolls_back_when_application_write_fails(
    bill_agent_context, monkeypatch
):
    client, _actor, database = bill_agent_context
    task = submit(client, "暂停云盘会员", "subscription-rollback")

    def fail_change(*_args, **_kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(agent_application, "change_subscription_status", fail_change)
    response = confirm(client, task)
    assert response.status_code == 500

    with database.session_factory() as session:
        subscription = session.scalar(
            select(Subscription).where(Subscription.merchant == "云盘会员")
        )
        task_id = UUID(task["id"])
        agent_task = session.get(AgentTask, task_id)
        challenge = session.get(ConfirmationChallenge, UUID(task["confirmation"]["id"]))
        execution = session.scalar(select(ToolExecution).where(ToolExecution.task_id == task_id))
        assert subscription is not None and subscription.status == "active"
        assert agent_task is not None and agent_task.status == "awaiting_confirmation"
        assert challenge is not None and challenge.status == "pending"
        assert execution is not None and execution.status == "awaiting_confirmation"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "subscription.status_changed")
            )
            == 0
        )


def test_concurrent_subscription_confirmations_have_one_status_change(bill_agent_context):
    client, _actor, database = bill_agent_context
    task = submit(client, "取消网易云音乐会员自动续费", "subscription-concurrent-confirm")

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _index: confirm(client, task), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    with database.session_factory() as session:
        subscription = session.scalar(
            select(Subscription).where(Subscription.merchant == "网易云音乐会员")
        )
        assert subscription is not None and subscription.status == "cancelled"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.resource_id == subscription.id,
                    AuditEvent.event_type == "subscription.status_changed",
                )
            )
            == 1
        )
