import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from finorch_api.agent.providers import ProviderSelection
from finorch_api.agent.runtime import FakeProvider, ModelToolCall, ModelTurn
from finorch_api.api.v1.agent import get_provider_selection
from finorch_api.infrastructure.database import get_db_session
from finorch_api.infrastructure.models import (
    Account,
    AuditEvent,
    Card,
    ConfirmationChallenge,
    InvestmentHolding,
    InvestmentOrder,
    Subscription,
    ToolExecution,
)
from finorch_api.main import app
from finorch_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DemoActor,
    get_current_demo_actor,
)
from sqlalchemy import func, select, update

CONVERSATION_ID = "30000000-0000-4000-8000-000000000001"
SOURCE_ACCOUNT_ID = UUID("10000000-0000-4000-8000-000000000001")


@pytest.fixture
def workflow_context(seeded_database):
    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_ONE_ID)
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        FakeProvider(), "fake"
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, seeded_database
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)
        app.dependency_overrides.pop(get_provider_selection, None)


def submit(client: TestClient, prompt: str, key: str) -> dict:
    response = client.post(
        "/api/v1/agent/tasks",
        json={"request_text": prompt, "conversation_id": CONVERSATION_ID},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client: TestClient, task: dict):
    challenge = task["confirmation"]
    assert challenge is not None
    return client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json={
            "challenge_id": challenge["id"],
            "parameters_hash": challenge["parameters_hash"],
        },
        headers={"Idempotency-Key": challenge["idempotency_key"]},
    )


def result(task: dict, name: str) -> dict:
    return next(
        step["result_data"]
        for step in reversed(task["steps"])
        if step.get("tool_name") == name and step.get("result_data") is not None
    )


class _StopOnceAfterCardFreezeProvider:
    mode = "openai-compatible"

    def __init__(self) -> None:
        self.delegate = FakeProvider()
        self.stopped_once = False

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        context = {}
        for message in messages:
            content = message.get("content")
            prefix = "Trusted demo context: "
            if message.get("role") == "system" and isinstance(content, str):
                if content.startswith(prefix):
                    context = json.loads(content[len(prefix) :])
                    break
        succeeded = {
            item.get("tool_name")
            for item in context.get("task_progress", {}).get("tools", [])
            if isinstance(item, dict) and item.get("status") == "succeeded"
        }
        if (
            not self.stopped_once
            and "card.freeze" in succeeded
            and "subscription.pause" not in succeeded
        ):
            self.stopped_once = True
            return ModelTurn("已处理。")
        return self.delegate.complete(messages, tools)


class _UnknownPayeeWriteAttemptProvider:
    mode = "openai-compatible"

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        del messages, tools
        return ModelTurn(
            None,
            (
                ModelToolCall("payees", "transfer.payees", "{}"),
                ModelToolCall(
                    "write",
                    "transfer.create",
                    '{"recipient_name":"张三","amount_minor":10000}',
                ),
            ),
        )


class _InvestmentBuyProvider:
    mode = "openai-compatible"

    def __init__(self, *, lookup_first: bool) -> None:
        self.lookup_first = lookup_first
        self.calls = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        del messages, tools
        self.calls += 1
        if self.lookup_first and self.calls == 1:
            return ModelTurn(None, (ModelToolCall("products", "investment.products", "{}"),))
        return ModelTurn(
            None,
            (
                ModelToolCall(
                    "buy",
                    "investment.buy",
                    '{"product_name":"成长指数模拟","amount_minor":100000}',
                ),
            ),
        )


class _InvalidPaydayPlanProvider:
    mode = "openai-compatible"

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        del messages, tools
        return ModelTurn(
            None,
            (ModelToolCall("plan", "finance.payday_plan", "{}"),),
        )


class _CountingNoopProvider:
    mode = "openai-compatible"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        del messages, tools
        self.calls += 1
        return ModelTurn("No tool call.")


def tool_names(task: dict) -> list[str]:
    return [step["tool_name"] for step in task["steps"] if step.get("tool_name")]


def test_suspicious_charge_workflow_pauses_at_two_confirmations_and_resumes(
    workflow_context,
) -> None:
    client, database = workflow_context
    task = submit(
        client,
        "帮我处理可疑扣款：查询异常账单和自动扣费，冻结相关银行卡并暂停对应代扣",
        "cross-suspicious-charge",
    )
    assert task["status"] == "awaiting_confirmation"
    assert tool_names(task) == [
        "bill.anomalies",
        "subscription.list",
        "card.freeze",
    ]
    assert any(
        "重复扣费提示" in item["anomaly_reason"] for item in result(task, "bill.anomalies")["items"]
    )
    assert task["confirmation"]["resource_type"] == "card"
    assert task["confirmation"]["resource_label"] == "Everyday debit"

    first = confirm(client, task)
    assert first.status_code == 200, first.text
    task = first.json()
    assert task["status"] == "awaiting_confirmation"
    assert tool_names(task)[-1] == "subscription.pause"
    assert task["confirmation"]["resource_type"] == "subscription"
    assert task["confirmation"]["resource_label"] == "腾讯视频会员"
    with database.session_factory() as session:
        card = session.get(Card, UUID("20000000-0000-4000-8000-000000000001"))
        subscription = session.scalar(
            select(Subscription).where(Subscription.merchant == "腾讯视频会员")
        )
        assert card is not None and card.status.value == "frozen"
        assert subscription is not None and subscription.status == "active"

    second = confirm(client, task)
    assert second.status_code == 200, second.text
    task = second.json()
    assert task["status"] == "completed"
    assert {"card.freeze", "subscription.pause"} <= set(tool_names(task))
    with database.session_factory() as session:
        subscription = session.scalar(
            select(Subscription).where(Subscription.merchant == "腾讯视频会员")
        )
        assert subscription is not None and subscription.status == "paused"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ToolExecution)
                .where(
                    ToolExecution.task_id == UUID(task["id"]),
                    ToolExecution.tool_name.in_(("card.freeze", "subscription.pause")),
                    ToolExecution.status == "succeeded",
                )
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.event_type.in_(
                        ("card.status_changed", "subscription.status_changed")
                    )
                )
            )
            == 2
        )


def test_payday_workflow_uses_server_plan_and_two_confirmed_writes(workflow_context) -> None:
    client, database = workflow_context
    task = submit(
        client,
        "发薪日资金调度：给小林转 200 元，预留 3000 元，其余投资适合的产品",
        "cross-payday-schedule",
    )
    assert task["status"] == "awaiting_confirmation", task
    assert tool_names(task) == [
        "transfer.accounts",
        "bill.monthly_summary",
        "finance.payday_plan",
        "transfer.create",
    ]
    plan = result(task, "finance.payday_plan")
    assert plan["monthly_income_minor"] == 650_000
    assert plan["monthly_expense_minor"] == 2_003_500
    assert task["confirmation"]["resource_type"] == "transfer"
    assert task["confirmation"]["details"]["amount_minor"] == 20_000

    first = confirm(client, task)
    assert first.status_code == 200, first.text
    task = first.json()
    assert task["status"] == "awaiting_confirmation"
    assert "investment.products" in tool_names(task)
    assert task["confirmation"]["resource_type"] == "investment_order"
    assert task["confirmation"]["details"]["amount_minor"] == plan["investment_budget_minor"]

    second = confirm(client, task)
    assert second.status_code == 200, second.text
    task = second.json()
    assert task["status"] == "completed"
    names = tool_names(task)
    assert names.index("transfer.create") < names.index("investment.buy")
    assert names[-2:] == ["transfer.accounts", "investment.portfolio"]
    with database.session_factory() as session:
        source = session.get(Account, SOURCE_ACCOUNT_ID)
        assert source is not None
        assert source.balance_minor == plan["reserve_amount_minor"]
        assert (
            session.scalar(
                select(func.count())
                .select_from(InvestmentHolding)
                .where(InvestmentHolding.actor_id == DEMO_USER_ONE_ID)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ToolExecution)
                .where(
                    ToolExecution.task_id == UUID(task["id"]),
                    ToolExecution.tool_name.in_(("transfer.create", "investment.buy")),
                    ToolExecution.status == "succeeded",
                )
            )
            == 2
        )
        latest_balance = result(task, "transfer.accounts")["items"]
        latest_source_balance = next(
            item["balance_minor"] for item in latest_balance if item["id"] == str(SOURCE_ACCOUNT_ID)
        )
        assert latest_source_balance == source.balance_minor
        portfolio = result(task, "investment.portfolio")
        assert portfolio["invested_value_minor"] == plan["investment_budget_minor"]


def test_payday_clarification_preserves_goal_and_resumes_after_input(workflow_context) -> None:
    client, _ = workflow_context
    task = submit(
        client,
        "发薪日帮我规划资金，给小林转一部分，剩余买适合我的理财。",
        "cross-payday-clarify",
    )
    assert task["status"] == "awaiting_input", task
    assert set(tool_names(task)) <= {"transfer.accounts", "bill.monthly_summary"}

    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/input",
        json={"request_text": "给小林转 200 元，账户预留 3000 元，其余买入适合我的模拟理财。"},
        headers={"Idempotency-Key": "cross-payday-clarify-input"},
    )
    assert response.status_code == 200, response.text
    task = response.json()
    assert task["status"] == "awaiting_confirmation", task
    assert "finance.payday_plan" in tool_names(task)
    assert task["confirmation"]["resource_type"] == "transfer"


def test_incomplete_confirmed_workflow_replans_before_marking_complete(workflow_context) -> None:
    client, _ = workflow_context
    provider = _StopOnceAfterCardFreezeProvider()
    previous_override = app.dependency_overrides[get_provider_selection]
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        provider, provider.mode
    )
    try:
        task = submit(
            client,
            "处置重复扣费提示，冻结关联银行卡并暂停对应订阅。",
            "cross-replan-after-confirm",
        )
        assert task["status"] == "awaiting_confirmation"
        task = confirm(client, task).json()
        assert provider.stopped_once
        assert task["status"] == "awaiting_confirmation", task
        assert tool_names(task)[-1] == "subscription.pause"
    finally:
        app.dependency_overrides[get_provider_selection] = previous_override


def test_unknown_payee_write_attempt_is_rejected_and_requests_clarification(
    workflow_context,
) -> None:
    client, database = workflow_context
    previous_override = app.dependency_overrides[get_provider_selection]
    provider = _UnknownPayeeWriteAttemptProvider()
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        provider, provider.mode
    )
    try:
        task = submit(client, "给张三转 100 元。", "cross-unknown-payee-rejected")
        assert task["status"] == "awaiting_input", task
        assert task["error_code"] is None
        assert task["confirmation"] is None
        assert "transfer.create" in tool_names(task)
        with database.session_factory() as session:
            source = session.get(Account, SOURCE_ACCOUNT_ID)
            assert source is not None and source.balance_minor == 1_250_000
            assert (
                session.scalar(
                    select(ConfirmationChallenge).where(
                        ConfirmationChallenge.task_id == UUID(task["id"])
                    )
                )
                is None
            )
    finally:
        app.dependency_overrides[get_provider_selection] = previous_override


@pytest.mark.parametrize(
    ("lookup_first", "expected_error"),
    [
        (False, "investment_suitability_not_verified"),
        (True, "risk_mismatch"),
    ],
)
def test_investment_buy_requires_a_server_checked_suitable_product(
    workflow_context, lookup_first: bool, expected_error: str
) -> None:
    client, database = workflow_context
    previous_override = app.dependency_overrides[get_provider_selection]
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        _InvestmentBuyProvider(lookup_first=lookup_first), "openai-compatible"
    )
    try:
        task = submit(client, "申购 1000 元成长指数模拟", f"investment-risk-{lookup_first}")
    finally:
        app.dependency_overrides[get_provider_selection] = previous_override

    assert task["status"] == "failed"
    assert task["error_code"] == expected_error
    assert task["confirmation"] is None
    assert "investment.buy" in tool_names(task)

    with database.session_factory() as session:
        source = session.get(Account, SOURCE_ACCOUNT_ID)
        assert source is not None and source.balance_minor == 1_250_000
        assert session.scalar(select(func.count()).select_from(InvestmentHolding)) == 0
        assert session.scalar(select(func.count()).select_from(InvestmentOrder)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(ConfirmationChallenge)
                .where(ConfirmationChallenge.task_id == UUID(task["id"]))
            )
            == 0
        )


def test_invalid_plan_arguments_request_user_input_without_marking_task_failed(
    workflow_context,
) -> None:
    client, database = workflow_context
    previous_override = app.dependency_overrides[get_provider_selection]
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        _InvalidPaydayPlanProvider(), "openai-compatible"
    )
    try:
        task = submit(
            client,
            "发薪日资金调度，给小林转 200 元，预留 3000 元，其余买入模拟理财。",
            "invalid-plan-needs-input",
        )
    finally:
        app.dependency_overrides[get_provider_selection] = previous_override

    assert task["status"] == "awaiting_input"
    assert task["error_code"] is None
    assert task["confirmation"] is None
    assert "收款人" in task["message"]
    assert tool_names(task) == ["finance.payday_plan"]

    with database.session_factory() as session:
        source = session.get(Account, SOURCE_ACCOUNT_ID)
        assert source is not None and source.balance_minor == 1_250_000
        assert session.scalar(select(func.count()).select_from(InvestmentHolding)) == 0
        assert session.scalar(select(func.count()).select_from(InvestmentOrder)) == 0


def test_incomplete_payday_parameters_clarify_before_any_tool_or_confirmation(
    workflow_context,
) -> None:
    client, database = workflow_context
    provider = _CountingNoopProvider()
    previous_override = app.dependency_overrides[get_provider_selection]
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        provider, "openai-compatible"
    )
    try:
        task = submit(
            client,
            "工资到账后给小林转 200 元，余下帮我安排成合适的模拟理财。",
            "incomplete-payday-clarification",
        )
    finally:
        app.dependency_overrides[get_provider_selection] = previous_override

    assert task["status"] == "awaiting_input"
    assert task["confirmation"] is None
    assert task["error_code"] is None
    assert tool_names(task) == []
    assert provider.calls == 0

    with database.session_factory() as session:
        source = session.get(Account, SOURCE_ACCOUNT_ID)
        assert source is not None and source.balance_minor == 1_250_000
        assert session.scalar(select(func.count()).select_from(InvestmentHolding)) == 0
        assert session.scalar(select(func.count()).select_from(InvestmentOrder)) == 0


def test_cancel_between_confirmations_keeps_completed_step_and_invalidates_next(
    workflow_context,
) -> None:
    client, database = workflow_context
    task = submit(
        client,
        "帮我处理可疑扣款，冻结相关卡并暂停对应自动扣费",
        "cross-cancel-between-steps",
    )
    task = confirm(client, task).json()
    assert task["status"] == "awaiting_confirmation"
    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/cancel",
        headers={"Idempotency-Key": "cancel-between-confirmations"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    with database.session_factory() as session:
        card = session.get(Card, UUID("20000000-0000-4000-8000-000000000001"))
        subscription = session.scalar(
            select(Subscription).where(Subscription.merchant == "腾讯视频会员")
        )
        challenge = session.get(ConfirmationChallenge, UUID(task["confirmation"]["id"]))
        assert card is not None and card.status.value == "frozen"
        assert subscription is not None and subscription.status == "active"
        assert challenge is not None and challenge.status == "cancelled"


def test_failed_second_step_can_resume_without_repeating_first_write(workflow_context) -> None:
    client, database = workflow_context
    task = submit(
        client,
        "帮我处理可疑扣款，冻结相关卡并暂停对应自动扣费",
        "cross-recover-partial-write",
    )
    task = confirm(client, task).json()
    assert task["status"] == "awaiting_confirmation"
    subscription_id = UUID(task["confirmation"]["resource_id"])
    with database.session_factory.begin() as session:
        session.execute(
            update(Subscription)
            .where(Subscription.id == subscription_id)
            .values(version=Subscription.version + 1)
        )

    stale = confirm(client, task)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "subscription_version_conflict"
    failed = client.get(f"/api/v1/agent/tasks/{task['id']}").json()
    assert failed["status"] == "failed"

    resumed = client.post(
        f"/api/v1/agent/tasks/{task['id']}/input",
        json={"request_text": "请继续暂停腾讯视频会员"},
        headers={"Idempotency-Key": "resume-partial-write"},
    )
    assert resumed.status_code == 200, resumed.text
    task = resumed.json()
    assert task["status"] == "awaiting_confirmation"
    assert task["confirmation"]["resource_type"] == "subscription"
    assert sum(name == "card.freeze" for name in tool_names(task)) == 1

    done = confirm(client, task)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    with database.session_factory() as session:
        subscription = session.get(Subscription, subscription_id)
        assert subscription is not None and subscription.status == "paused"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ToolExecution)
                .where(
                    ToolExecution.task_id == UUID(task["id"]),
                    ToolExecution.tool_name == "card.freeze",
                    ToolExecution.status == "succeeded",
                )
            )
            == 1
        )
