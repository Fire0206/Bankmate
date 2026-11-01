import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from bankmate_api.agent.providers import ProviderSelection
from bankmate_api.agent.runtime import FakeProvider, LLMProvider, ModelToolCall, ModelTurn
from bankmate_api.api.v1.agent import get_provider_selection
from bankmate_api.application.transactions import write_transaction
from bankmate_api.infrastructure.database import get_db_session
from bankmate_api.infrastructure.models import (
    Account,
    AuditEvent,
    ConfirmationChallenge,
    DemoUser,
    InvestmentHolding,
    InvestmentOrder,
    SplitBill,
    SplitParticipant,
    Transaction,
    Transfer,
    utc_now,
)
from bankmate_api.main import app
from bankmate_api.security.circuit import active_write_hold
from bankmate_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DEMO_USER_TWO_ID,
    DemoActor,
    get_current_demo_actor,
)
from bankmate_api.security.verification import issue_demo_code
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

ALICE_SOURCE_ACCOUNT = UUID("10000000-0000-4000-8000-000000000001")
ALICE_SAVINGS_ACCOUNT = UUID("10000000-0000-4000-8000-000000000002")
BOB_ACCOUNT = UUID("10000000-0000-4000-8000-000000000003")


@pytest.fixture
def banking_api(seeded_database):
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


def submit(client: TestClient, request_text: str, key: str) -> dict:
    response = client.post(
        "/api/v1/agent/tasks",
        json={"request_text": request_text},
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


def balances(database) -> dict[UUID, int]:
    with database.session_factory() as session:
        return {
            account.id: account.balance_minor
            for account in session.scalars(select(Account).order_by(Account.id))
        }


def test_transfer_requires_confirmation_and_writes_balanced_transactions(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)

    task = submit(client, "给小林转 100 元", "transfer-basic")
    assert task["status"] == "awaiting_confirmation", task
    assert task["confirmation"]["resource_type"] == "transfer"
    assert task["confirmation"]["details"]["amount_minor"] == 10_000
    assert balances(database) == before

    response = confirm(client, task)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed", response.text
    assert balances(database)[ALICE_SOURCE_ACCOUNT] == before[ALICE_SOURCE_ACCOUNT] - 10_000
    assert balances(database)[BOB_ACCOUNT] == before[BOB_ACCOUNT] + 10_000

    with database.session_factory() as session:
        rows = list(
            session.scalars(select(Transaction).where(Transaction.synthetic_ref.like("transfer:%")))
        )
        assert len(rows) == 2
        assert {row.amount_minor for row in rows} == {10_000}
        assert {row.entry_kind for row in rows} == {"transfer"}
        assert {row.direction for row in rows} == {"income", "expense"}
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "transfer.executed")
        )
        assert event is not None and event.outcome == "succeeded"
        challenge = session.get(ConfirmationChallenge, UUID(task["confirmation"]["id"]))
        assert challenge is not None and challenge.status == "consumed"

    after_first_confirmation = balances(database)
    repeated = confirm(client, task)
    assert repeated.status_code == 200
    assert balances(database) == after_first_confirmation
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.synthetic_ref.like("transfer:%"))
            )
            == 2
        )


def test_phone_transfer_remark_is_confirmed_persisted_and_actor_scoped(banking_api) -> None:
    client, actor, database = banking_api
    before = balances(database)
    payees = client.get("/api/v1/payees").json()["items"]
    assert any(item["phone_masked"] == "199****1042" for item in payees)
    assert all("phone_number" not in item for item in payees)

    task = submit(client, "给手机号19900001042转100元，备注午餐", "phone-transfer-note")
    assert task["status"] == "awaiting_confirmation", task
    assert task["confirmation"]["details"]["payee_name"] == "小林"
    assert task["confirmation"]["details"]["remark"] == "午餐"
    assert balances(database) == before
    result = confirm(client, task)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    assert balances(database)[ALICE_SOURCE_ACCOUNT] == before[ALICE_SOURCE_ACCOUNT] - 10_000
    history = client.get("/api/v1/transfers").json()["items"]
    assert history[0]["remark"] == "午餐"
    with database.session_factory() as session:
        transfer = session.scalar(select(Transfer).where(Transfer.id == UUID(history[0]["id"])))
        assert transfer is not None and transfer.remark == "午餐"
        assert transfer.payee_name == "小林"

    actor[0] = DEMO_USER_TWO_ID
    foreign = submit(client, "给手机号19900001042转10元", "foreign-phone-transfer")
    assert foreign["status"] == "failed"
    assert foreign["error_code"] == "payee_not_found"
    assert foreign["confirmation"] is None


def test_phone_transfer_rejects_missing_or_different_target(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    missing = submit(client, "给手机号19900009999转10元", "missing-phone-payee")
    assert missing["status"] == "failed"
    assert missing["error_code"] == "payee_not_found"

    class DifferentPhoneProvider(LLMProvider):
        def complete(self, messages, tools):
            return ModelTurn(
                "",
                (
                    ModelToolCall(
                        "wrong-phone",
                        "transfer.create",
                        json.dumps({"recipient_phone": "19900001042", "amount_minor": 1000}),
                    ),
                ),
            )

    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        DifferentPhoneProvider(), "openai-compatible"
    )
    changed = submit(client, "给手机号19900002729转10元", "changed-phone-target")
    assert changed["status"] == "failed"
    assert changed["error_code"] == "transfer_target_mismatch"
    assert changed["confirmation"] is None
    assert balances(database) == before


def test_remark_change_invalidates_pending_confirmation(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    task = submit(client, "给小林转10元，备注原用途", "remark-tamper")
    assert task["status"] == "awaiting_confirmation"
    assert task["confirmation"]["details"]["remark"] == "原用途"
    with database.session_factory() as session:
        with write_transaction(session, immediate=True):
            session.execute(
                update(Transfer)
                .where(Transfer.id == UUID(task["confirmation"]["resource_id"]))
                .values(remark="被改动的用途")
            )
    response = confirm(client, task)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "transfer_version_conflict"
    assert balances(database) == before


def test_saved_payee_phone_validation_and_uniqueness(banking_api) -> None:
    client, _actor, _database = banking_api
    body = {
        "display_name": "测试收款人",
        "destination_account_id": str(BOB_ACCOUNT),
        "phone_number": "19900008888",
    }
    saved = client.post("/api/v1/payees", json=body)
    assert saved.status_code == 201, saved.text
    assert saved.json()["phone_masked"] == "199****8888"
    assert "phone_number" not in saved.json()
    duplicate = client.post("/api/v1/payees", json={**body, "display_name": "另一位"})
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "payee_phone_exists"
    invalid = client.post(
        "/api/v1/payees", json={**body, "display_name": "错误号码", "phone_number": "123"}
    )
    assert invalid.status_code == 422


def test_high_value_transfer_requires_simulated_second_verification(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    task = submit(client, "给小林转 2000 元", "high-value-verification")
    challenge = task["confirmation"]
    assert challenge["risk_level"] == "red"
    assert challenge["confirmation_method"] == "demo_otp"

    missing = confirm(client, task)
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "strong_verification_required"
    assert balances(database) == before

    with database.session_factory() as session:
        with write_transaction(session, immediate=True):
            _, code = issue_demo_code(
                session,
                actor_id=DEMO_USER_ONE_ID,
                confirmation_id=UUID(challenge["id"]),
                now=utc_now(),
            )
    wrong = "000000" if code != "000000" else "999999"
    for _ in range(2):
        rejected = client.post(
            f"/api/v1/agent/tasks/{task['id']}/confirm",
            json={
                "challenge_id": challenge["id"],
                "parameters_hash": challenge["parameters_hash"],
                "verification_code": wrong,
            },
            headers={"Idempotency-Key": challenge["idempotency_key"]},
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "verification_incorrect"
    assert balances(database) == before

    approved = client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json={
            "challenge_id": challenge["id"],
            "parameters_hash": challenge["parameters_hash"],
            "verification_code": code,
        },
        headers={"Idempotency-Key": challenge["idempotency_key"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "completed"
    assert balances(database)[ALICE_SOURCE_ACCOUNT] == before[ALICE_SOURCE_ACCOUNT] - 200_000
    assert confirm(client, task).status_code == 200
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Transfer).where(Transfer.status == "executed")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "security.risk_decision")
            )
            >= 4
        )


def test_daily_cumulative_transfer_escalates_before_second_execution(banking_api) -> None:
    client, _actor, database = banking_api
    first = submit(client, "给小林转 600 元", "daily-first")
    assert first["confirmation"]["risk_level"] == "yellow"
    second = submit(client, "给小林转 500 元", "daily-second")
    assert second["confirmation"]["risk_level"] == "yellow"
    assert confirm(client, first).status_code == 200
    after_first = balances(database)
    refreshed = client.get(f"/api/v1/agent/tasks/{second['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["confirmation"]["risk_level"] == "red"
    refused = confirm(client, second)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "strong_verification_required"
    assert balances(database) == after_first


def test_concurrent_high_risk_confirmation_has_one_financial_effect(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    task = submit(client, "给小林转 2000 元", "concurrent-high-risk")
    challenge = task["confirmation"]
    with database.session_factory() as session:
        with write_transaction(session, immediate=True):
            _, code = issue_demo_code(
                session,
                actor_id=DEMO_USER_ONE_ID,
                confirmation_id=UUID(challenge["id"]),
                now=utc_now(),
            )

    def send_confirmation(_index: int):
        return client.post(
            f"/api/v1/agent/tasks/{task['id']}/confirm",
            json={
                "challenge_id": challenge["id"],
                "parameters_hash": challenge["parameters_hash"],
                "verification_code": code,
            },
            headers={"Idempotency-Key": challenge["idempotency_key"]},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send_confirmation, range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert balances(database)[ALICE_SOURCE_ACCOUNT] == before[ALICE_SOURCE_ACCOUNT] - 200_000
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Transfer).where(Transfer.status == "executed")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.synthetic_ref.like("transfer:%"))
            )
            == 2
        )


def test_repeated_bad_verification_holds_writes_but_not_owned_reads(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    future = (utc_now() + timedelta(days=2)).replace(microsecond=0)
    scheduled = submit(
        client,
        f"请在 {future:%Y-%m-%d %H:%M} 给小林定时转 50 元",
        "scheduled-before-hold",
    )
    assert confirm(client, scheduled).status_code == 200
    with database.session_factory.begin() as session:
        due_transfer = session.scalar(select(Transfer).where(Transfer.status == "scheduled"))
        assert due_transfer is not None
        due_transfer.scheduled_at = utc_now() - timedelta(minutes=1)
    task = submit(client, "给小林转 2000 元", "bad-code-hold")
    challenge = task["confirmation"]
    with database.session_factory() as session:
        with write_transaction(session, immediate=True):
            _, code = issue_demo_code(
                session,
                actor_id=DEMO_USER_ONE_ID,
                confirmation_id=UUID(challenge["id"]),
                now=utc_now(),
            )
    wrong = "000000" if code != "000000" else "999999"
    for _ in range(3):
        response = client.post(
            f"/api/v1/agent/tasks/{task['id']}/confirm",
            json={
                "challenge_id": challenge["id"],
                "parameters_hash": challenge["parameters_hash"],
                "verification_code": wrong,
            },
            headers={"Idempotency-Key": challenge["idempotency_key"]},
        )
        assert response.status_code == 409
    with database.session_factory() as session:
        assert active_write_hold(session, actor_id=DEMO_USER_ONE_ID) is not None
        assert active_write_hold(session, actor_id=DEMO_USER_TWO_ID) is None

    assert client.get("/api/v1/cards").status_code == 200
    read_task = submit(client, "查看我的银行卡", "read-during-hold")
    assert read_task["status"] == "completed"
    blocked = client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json={
            "challenge_id": challenge["id"],
            "parameters_hash": challenge["parameters_hash"],
            "verification_code": code,
        },
        headers={"Idempotency-Key": challenge["idempotency_key"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "safety_hold_active"
    assert balances(database) == before
    due_response = client.post("/api/v1/simulate-due")
    assert due_response.status_code == 200
    assert due_response.json()["executed_count"] == 0
    with database.session_factory() as session:
        assert session.scalar(select(Transfer).where(Transfer.status == "scheduled")) is not None


def test_transfer_insufficient_funds_and_actor_scoped_reads(banking_api) -> None:
    client, actor, database = banking_api
    task = submit(client, "给小林转 99999999 元", "transfer-insufficient")
    assert task["status"] == "failed", task
    assert task["error_code"] == "insufficient_funds"

    actor[0] = DEMO_USER_TWO_ID
    own_accounts = client.get("/api/v1/accounts").json()["items"]
    assert [item["id"] for item in own_accounts] == [str(BOB_ACCOUNT)]
    product_page = client.get("/api/v1/investments/products").json()
    assert product_page["risk_level"] == 1
    assert len(product_page["items"]) == 3

    assert balances(database)[ALICE_SOURCE_ACCOUNT] == 1_250_000
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Transfer)) == 0


def test_scheduled_transfer_is_confirmed_then_simulated_only_when_due(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    future = (utc_now() + timedelta(days=2)).replace(microsecond=0)
    date_text = future.strftime("%Y-%m-%d %H:%M")
    task = submit(
        client,
        f"请在 {date_text} 给小林定时转 50 元",
        "transfer-schedule",
    )
    assert task["status"] == "awaiting_confirmation"
    assert task["steps"][-1]["tool_name"] == "transfer.schedule"
    scheduled = confirm(client, task)
    assert scheduled.status_code == 200
    assert scheduled.json()["status"] == "completed", scheduled.text
    assert balances(database) == before

    with database.session_factory.begin() as session:
        transfer = session.scalar(select(Transfer).where(Transfer.status == "scheduled"))
        assert transfer is not None
        transfer.scheduled_at = datetime.now(UTC) - timedelta(minutes=1)

    simulated = client.post("/api/v1/simulate-due")
    assert simulated.status_code == 200, simulated.text
    assert simulated.json()["executed_count"] == 1
    assert balances(database)[ALICE_SOURCE_ACCOUNT] == before[ALICE_SOURCE_ACCOUNT] - 5_000
    assert balances(database)[BOB_ACCOUNT] == before[BOB_ACCOUNT] + 5_000

    after_execution = balances(database)
    later = (utc_now() + timedelta(days=3)).replace(microsecond=0)
    later_task = submit(
        client,
        f"请在 {later:%Y-%m-%d %H:%M} 给小林定时转 20 元",
        "transfer-schedule-cancel",
    )
    assert confirm(client, later_task).status_code == 200
    cancel_task = submit(client, "取消给小林的定时转账", "transfer-cancel")
    assert cancel_task["status"] == "awaiting_confirmation"
    assert cancel_task["confirmation"]["target_status"] == "cancelled"
    cancelled = confirm(client, cancel_task)
    assert cancelled.status_code == 200
    assert balances(database) == after_execution
    with database.session_factory() as session:
        assert session.scalar(select(Transfer).where(Transfer.status == "cancelled")) is not None


def test_scheduled_transfer_rechecks_risk_at_execution(banking_api) -> None:
    client, _actor, database = banking_api
    future = (utc_now() + timedelta(days=2)).replace(microsecond=0)
    scheduled = submit(
        client,
        f"请在 {future:%Y-%m-%d %H:%M} 给小林定时转 600 元",
        "scheduled-risk",
    )
    assert confirm(client, scheduled).status_code == 200
    immediate = submit(client, "给小林转 600 元", "immediate-before-due")
    assert confirm(client, immediate).status_code == 200
    before_due = balances(database)
    with database.session_factory.begin() as session:
        transfer = session.scalar(select(Transfer).where(Transfer.status == "scheduled"))
        assert transfer is not None
        transfer.scheduled_at = utc_now() - timedelta(minutes=1)

    response = client.post("/api/v1/simulate-due")
    assert response.status_code == 200
    assert response.json()["executed_count"] == 0
    assert balances(database) == before_due
    with database.session_factory() as session:
        failed = session.scalar(select(Transfer).where(Transfer.status == "failed"))
        assert failed is not None
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "transfer.simulated_execution_failed")
        )
        assert audit is not None
        assert audit.after_state["error_code"] == "strong_verification_required"


def test_scheduled_transfer_failure_after_debit_rolls_back_that_transfer(
    banking_api, monkeypatch
) -> None:
    client, _actor, database = banking_api
    future = (utc_now() + timedelta(days=2)).replace(microsecond=0)
    task = submit(
        client,
        f"请在 {future:%Y-%m-%d %H:%M} 给小林定时转 50 元",
        "scheduled-partial-debit-rollback",
    )
    assert confirm(client, task).status_code == 200
    with database.session_factory.begin() as session:
        transfer = session.scalar(select(Transfer).where(Transfer.status == "scheduled"))
        assert transfer is not None
        transfer.scheduled_at = utc_now() - timedelta(minutes=1)
        transfer_id = transfer.id

    before = balances(database)
    from bankmate_api.application import transfers as transfer_application

    original_delta = transfer_application._account_delta
    calls = 0

    def fail_destination(session, *, account_id, amount_minor):
        nonlocal calls
        calls += 1
        if calls == 2:
            return False
        return original_delta(session, account_id=account_id, amount_minor=amount_minor)

    monkeypatch.setattr(transfer_application, "_account_delta", fail_destination)
    response = client.post("/api/v1/simulate-due")
    assert response.status_code == 200, response.text
    assert response.json()["executed_count"] == 0
    assert calls == 2
    assert balances(database) == before
    with database.session_factory() as session:
        transfer = session.get(Transfer, transfer_id)
        assert transfer is not None and transfer.status == "failed"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.synthetic_ref.like(f"transfer:{transfer_id}:%"))
            )
            == 0
        )
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "transfer.simulated_execution_failed",
                AuditEvent.resource_id == transfer_id,
            )
        )
        assert audit is not None
        assert audit.after_state["error_code"] == "destination_not_found"


def test_scheduled_transfer_one_year_limit_handles_leap_day(banking_api, monkeypatch) -> None:
    client, _actor, _database = banking_api
    leap_day_now = datetime(2024, 2, 29, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("bankmate_api.application.transfers.utc_now", lambda: leap_day_now)

    class ScheduledTransferProvider(LLMProvider):
        mode = "openai-compatible"

        def complete(self, messages, tools):
            del messages, tools
            return ModelTurn(
                "",
                (
                    ModelToolCall(
                        "schedule-leap-day",
                        "transfer.schedule",
                        '{"recipient_name":"小林","amount_minor":2000,'
                        '"scheduled_at":"2025-02-28T00:00:00+00:00"}',
                    ),
                ),
            )

    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        ScheduledTransferProvider(), "openai-compatible"
    )
    try:
        response = client.post(
            "/api/v1/agent/tasks",
            json={
                "request_text": "2025-02-28 00:00 给小林定时转账 20 元",
                "conversation_id": str(UUID(int=4)),
            },
            headers={"Idempotency-Key": "schedule-after-leap-day"},
        )
    finally:
        app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
            FakeProvider(), "fake"
        )

    assert response.status_code == 200, response.text
    task = response.json()
    assert task["status"] == "awaiting_confirmation"
    assert task["confirmation"]["details"]["scheduled_at"] == "2025-02-28T00:00:00+00:00"


def test_aa_split_rounds_minor_units_and_requires_collection_confirmation(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    task = submit(
        client,
        "创建火锅AA分账 100 元，和小王、小李",
        "split-create",
    )
    assert task["status"] == "awaiting_confirmation"
    details = task["steps"][-1]["result_data"]
    assert details["shares_minor"] == [3334, 3333, 3333]
    assert sum(details["shares_minor"]) == 10_000
    assert balances(database) == before

    opened = confirm(client, task)
    assert opened.status_code == 200
    assert opened.json()["status"] == "completed"
    assert balances(database)[ALICE_SOURCE_ACCOUNT] == before[ALICE_SOURCE_ACCOUNT] - 10_000

    history = submit(client, "查看我的 AA 分账", "split-history")
    assert history["status"] == "completed"
    split_items = history["steps"][-1]["result_data"]["items"]
    assert len(split_items) == 1
    assert split_items[0]["title"] == "火锅"
    assert split_items[0]["participants"]

    with database.session_factory() as session:
        bill = session.scalar(select(SplitBill))
        assert bill is not None and bill.status == "open"
        participants = list(
            session.scalars(
                select(SplitParticipant).where(SplitParticipant.split_bill_id == bill.id)
            )
        )
        assert sum(item.amount_minor for item in participants) == bill.total_amount_minor
        assert sum(item.amount_minor for item in participants if item.status == "pending") == 6_666

    collect_task = submit(client, "收取火锅AA分账", "split-collect")
    assert collect_task["status"] == "awaiting_confirmation", collect_task
    assert collect_task["confirmation"]["target_status"] == "settled"
    settled = confirm(client, collect_task)
    assert settled.status_code == 200
    with database.session_factory() as session:
        bill = session.scalar(select(SplitBill))
        assert bill is not None and bill.status == "settled"
        assert all(
            item.status in {"organizer_paid", "paid"}
            for item in session.scalars(
                select(SplitParticipant).where(SplitParticipant.split_bill_id == bill.id)
            )
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "split.status_changed")
            )
            == 2
        )


@pytest.mark.parametrize(
    ("request_text", "expected_title", "expected_amount", "expected_participants"),
    [
        (
            "活动名是读书会聚餐，建立一笔315.60元AA分账，参与者为林岚、陈舟、王珂。",
            "读书会聚餐",
            31_560,
            {"林岚", "陈舟", "王珂"},
        ),
        (
            "请把周末羽毛球活动记作AA分账，合计178元，除我之外有陈舟和王珂参加。",
            "周末羽毛球活动",
            17_800,
            {"陈舟", "王珂"},
        ),
    ],
)
def test_phase2f_split_wording_preserves_title_total_and_people(
    banking_api,
    request_text: str,
    expected_title: str,
    expected_amount: int,
    expected_participants: set[str],
) -> None:
    client, _actor, database = banking_api
    task = submit(client, request_text, f"phase2f-split-{expected_amount}")

    assert task["status"] == "awaiting_confirmation", task
    confirmation = task["confirmation"]
    assert confirmation["resource_label"] == expected_title
    assert confirmation["details"]["total_amount_minor"] == expected_amount
    participant_names = {item["display_name"] for item in confirmation["details"]["participants"]}
    assert expected_participants <= participant_names
    assert "我" not in participant_names

    completed = confirm(client, task)
    assert completed.status_code == 200, completed.text
    with database.session_factory() as session:
        bill = session.scalar(select(SplitBill))
        assert bill is not None
        assert bill.title == expected_title
        assert bill.total_amount_minor == expected_amount
        persisted_names = {
            item.display_name
            for item in session.scalars(
                select(SplitParticipant).where(SplitParticipant.split_bill_id == bill.id)
            )
        }
        assert expected_participants <= persisted_names


def test_phase2f_compare_resolves_short_product_aliases(banking_api) -> None:
    client, _actor, _database = banking_api
    task = submit(client, "对比现金管理和短债组合", "phase2f-investment-aliases")

    assert task["status"] == "completed", task
    assert task["steps"][-1]["tool_name"] == "investment.compare"
    product_names = {item["name"] for item in task["steps"][-1]["result_data"]["items"]}
    assert product_names == {"安稳现金管理", "稳健短债组合"}


def test_split_proposal_with_model_added_operation_words_needs_clarification(banking_api) -> None:
    client, _actor, database = banking_api

    class AlteredSplitProvider(FakeProvider):
        def complete(self, messages, tools):
            del messages, tools
            return ModelTurn(
                "",
                (
                    ModelToolCall(
                        "wrong-title",
                        "transfer.split_create",
                        json.dumps(
                            {
                                "title": "火锅AA分账",
                                "amount_minor": 18_000,
                                "participant_names": ["小林", "小王", "平分"],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ),
            )

    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        AlteredSplitProvider(), "fake"
    )
    try:
        task = submit(
            client,
            "创建180元的火锅AA分账，和小林、小王平分",
            "split-altered-fields",
        )
    finally:
        app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
            FakeProvider(), "fake"
        )

    assert task["status"] == "awaiting_input", task
    assert task["confirmation"] is None
    assert "参与人" in task["message"] or "名称" in task["message"]
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(SplitBill)) == 0
        assert session.scalar(select(func.count()).select_from(ConfirmationChallenge)) == 0


def test_investment_purchase_and_redemption_update_cash_holdings_orders_and_audit(
    banking_api,
) -> None:
    client, _actor, database = banking_api
    before = balances(database)[ALICE_SOURCE_ACCOUNT]
    products = client.get("/api/v1/investments/products").json()["items"]
    safe_product = next(item for item in products if item["name"] == "安稳现金管理")
    risky_product = next(item for item in products if item["name"] == "成长指数模拟")
    assert safe_product["suitable"] is True
    assert risky_product["suitable"] is False

    task = submit(client, "申购安稳现金管理 100 元", "investment-buy")
    assert task["status"] == "awaiting_confirmation", task
    assert "模拟申购" in task["message"] and "转账" not in task["message"]
    assert task["confirmation"]["resource_type"] == "investment_order"
    assert task["confirmation"]["details"]["amount_minor"] == 10_000
    assert balances(database)[ALICE_SOURCE_ACCOUNT] == before
    bought = confirm(client, task)
    assert bought.status_code == 200
    assert balances(database)[ALICE_SOURCE_ACCOUNT] == before - 10_000
    portfolio_task = submit(client, "查看我的理财持仓和资产", "investment-portfolio-read")
    assert portfolio_task["status"] == "completed"
    portfolio_result = portfolio_task["steps"][-1]["result_data"]
    assert portfolio_result["invested_value_minor"] == 10_000
    assert portfolio_result["holdings"]
    portfolio = client.get("/api/v1/investments/portfolio").json()
    assert portfolio["invested_value_minor"] == 10_000
    assert portfolio["total_assets_minor"] == portfolio["cash_balance_minor"] + 10_000

    redeem_task = submit(client, "赎回安稳现金管理全部", "investment-redeem")
    assert redeem_task["status"] == "awaiting_confirmation"
    redeemed = confirm(client, redeem_task)
    assert redeemed.status_code == 200
    assert balances(database)[ALICE_SOURCE_ACCOUNT] == before
    assert client.get("/api/v1/investments/portfolio").json()["invested_value_minor"] == 0

    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(InvestmentOrder)) == 2
        holding = session.scalar(select(InvestmentHolding))
        assert holding is not None and holding.units_micros == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type.like("investment.%_executed"))
            )
            == 2
        )


def test_risk_mismatch_never_creates_an_investment_order(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    task = submit(client, "申购成长指数模拟 1000 元", "investment-risk-mismatch")
    assert task["status"] == "failed"
    assert task["error_code"] == "risk_mismatch"
    assert balances(database) == before
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(InvestmentOrder)) == 0


def test_high_risk_suitable_investment_still_requires_second_verification(banking_api) -> None:
    client, _actor, database = banking_api
    with database.session_factory.begin() as session:
        user = session.get(DemoUser, DEMO_USER_ONE_ID)
        assert user is not None
        user.risk_level = 4
    before = balances(database)
    task = submit(client, "申购成长指数模拟 1000 元", "high-risk-investment")
    assert task["status"] == "awaiting_confirmation", task
    assert task["confirmation"]["risk_level"] == "red"
    assert confirm(client, task).status_code == 409
    assert balances(database) == before
    with database.session_factory() as session:
        order = session.scalar(select(InvestmentOrder))
        assert order is not None and order.status == "awaiting_confirmation"


def test_investment_purchase_without_task_suitability_result_is_rejected(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)

    class DirectBuyProvider(FakeProvider):
        def complete(self, messages, tools):
            del messages, tools
            return ModelTurn(
                "",
                (
                    ModelToolCall(
                        "direct-buy-without-check",
                        "investment.buy",
                        json.dumps(
                            {"product_name": "安稳现金管理", "amount_minor": 10_000},
                            ensure_ascii=False,
                        ),
                    ),
                ),
            )

    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        DirectBuyProvider(), "fake"
    )
    try:
        task = submit(client, "申购安稳现金管理 100 元", "investment-without-risk-check")
    finally:
        app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
            FakeProvider(), "fake"
        )

    assert task["status"] == "failed"
    assert task["error_code"] == "investment_suitability_not_verified"
    assert task["confirmation"] is None
    assert balances(database) == before
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(InvestmentOrder)) == 0


def test_cancelled_proposals_do_not_remain_pending(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    transfer_task = submit(client, "给小林转 10 元", "cancel-pending-transfer")
    order_task = submit(client, "申购安稳现金管理 100 元", "cancel-pending-order")

    for task, key in ((transfer_task, "cancel-transfer"), (order_task, "cancel-order")):
        response = client.post(
            f"/api/v1/agent/tasks/{task['id']}/cancel",
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelled"

    assert balances(database) == before
    with database.session_factory() as session:
        assert session.scalar(select(Transfer).where(Transfer.status == "cancelled")) is not None
        assert (
            session.scalar(select(InvestmentOrder).where(InvestmentOrder.status == "cancelled"))
            is not None
        )


def test_expired_confirmation_records_correct_resource_and_cancels_proposal(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    task = submit(client, "给小林转 10 元", "expire-transfer")
    challenge_id = UUID(task["confirmation"]["id"])
    transfer_id = UUID(task["confirmation"]["resource_id"])
    with database.session_factory.begin() as session:
        challenge = session.get(ConfirmationChallenge, challenge_id)
        assert challenge is not None
        challenge.expires_at = utc_now() - timedelta(seconds=1)

    response = client.get(f"/api/v1/agent/tasks/{task['id']}")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "confirmation_expired"
    assert response.json()["confirmation"] is None
    assert balances(database) == before
    with database.session_factory() as session:
        transfer = session.get(Transfer, transfer_id)
        assert transfer is not None and transfer.status == "cancelled"
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "transfer.confirmation_expired")
        )
        assert event is not None and event.resource_id == transfer_id
        assert event.after_state["resource"]["status"] == "cancelled"


def test_transfer_database_failure_rolls_back_balances_challenge_and_audit(banking_api) -> None:
    client, _actor, database = banking_api
    before = balances(database)
    task = submit(client, "给小林转 25 元", "transfer-db-failure")
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_transfer_transactions "
            "BEFORE INSERT ON transactions WHEN NEW.entry_kind = 'transfer' "
            "BEGIN SELECT RAISE(ABORT, 'simulated database failure'); END"
        )

    response = confirm(client, task)
    assert response.status_code == 500
    assert balances(database) == before
    with database.session_factory() as session:
        transfer = session.get(Transfer, UUID(task["confirmation"]["resource_id"]))
        challenge = session.get(ConfirmationChallenge, UUID(task["confirmation"]["id"]))
        assert transfer is not None and transfer.status == "awaiting_confirmation"
        assert challenge is not None and challenge.status == "pending"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "transfer.executed")
            )
            == 0
        )
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER reject_transfer_transactions")


def test_payee_management_uses_owned_demo_identity(banking_api) -> None:
    client, _actor, database = banking_api
    accounts = client.get("/api/v1/accounts").json()["items"]
    assert {item["id"] for item in accounts} == {
        str(ALICE_SOURCE_ACCOUNT),
        str(ALICE_SAVINGS_ACCOUNT),
    }
    payees = client.get("/api/v1/payees").json()["items"]
    assert {item["display_name"] for item in payees} == {"小林", "储蓄账户"}

    destinations = client.get("/api/v1/transfer-destinations")
    assert destinations.status_code == 200
    destination_items = destinations.json()["items"]
    assert [item["id"] for item in destination_items] == [str(BOB_ACCOUNT)]
    assert set(destination_items[0]) == {"id", "label", "currency"}

    created = client.post(
        "/api/v1/payees",
        json={
            "display_name": "测试收款人",
            "destination_account_id": destination_items[0]["id"],
        },
    )
    assert created.status_code == 201, created.text
    payee_id = created.json()["id"]
    assert client.delete(f"/api/v1/payees/{payee_id}").status_code == 204
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.actor_id == DEMO_USER_ONE_ID)
            )
            == 0
        )


def test_newly_saved_payee_can_be_selected_by_agent_transfer(banking_api) -> None:
    client, _actor, _database = banking_api
    destination = client.get("/api/v1/transfer-destinations").json()["items"][0]
    created = client.post(
        "/api/v1/payees",
        json={
            "display_name": "邻居王",
            "destination_account_id": destination["id"],
        },
    )
    assert created.status_code == 201, created.text

    task = submit(client, "帮我给邻居王转账 520 元", "transfer-to-new-payee")

    assert task["status"] == "awaiting_confirmation", task
    assert task["confirmation"]["details"]["payee_name"] == "邻居王"
    assert task["confirmation"]["details"]["amount_minor"] == 52_000


def test_transfer_amount_only_followup_uses_saved_task_recipient(banking_api) -> None:
    client, _actor, database = banking_api
    destination = client.get("/api/v1/transfer-destinations").json()["items"][0]
    created = client.post(
        "/api/v1/payees",
        json={
            "display_name": "邻居王",
            "destination_account_id": destination["id"],
        },
    )
    assert created.status_code == 201, created.text

    before = balances(database)
    initial = submit(client, "给邻居王发起一笔转账，请询问金额", "transfer-amount-input")
    assert initial["status"] == "awaiting_input", initial
    assert initial["confirmation"] is None

    continuation = client.post(
        f"/api/v1/agent/tasks/{initial['id']}/input",
        json={"request_text": "520 元"},
        headers={"Idempotency-Key": "transfer-amount-only-followup"},
    )

    assert continuation.status_code == 200, continuation.text
    proposal = continuation.json()
    assert proposal["status"] == "awaiting_confirmation", proposal
    assert proposal["confirmation"]["details"]["payee_name"] == "邻居王"
    assert proposal["confirmation"]["details"]["amount_minor"] == 52_000
    assert proposal["confirmation"]["details"]["source_account_label"]
    with database.session_factory() as session:
        transfer = session.scalar(select(Transfer))
        assert transfer is not None and transfer.status == "awaiting_confirmation"
    assert balances(database) == before
