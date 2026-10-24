"""Confirmed synthetic card controls and purchases use real ledger rows."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from finorch_api.agent.providers import ProviderSelection
from finorch_api.agent.runtime import FakeProvider
from finorch_api.api.v1.agent import get_provider_selection
from finorch_api.application.transactions import write_transaction
from finorch_api.infrastructure.database import get_db_session
from finorch_api.infrastructure.models import (
    Account,
    AuditEvent,
    Card,
    StrongVerification,
    Transaction,
    utc_now,
)
from finorch_api.main import app
from finorch_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DEMO_USER_TWO_ID,
    DemoActor,
    get_current_demo_actor,
)
from finorch_api.security.verification import issue_demo_code
from sqlalchemy import func, select
from test_agent_api import ALICE_ACTIVE_CARD_ID, confirm, submit


@pytest.fixture
def shared_api_context(seeded_database):
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


def test_card_limit_change_then_purchase_updates_balance_and_audit(shared_api_context) -> None:
    client, actor, database = shared_api_context
    limit = submit(client, "把尾号1042的卡单笔限额改成1000元", key="limit-1000")
    assert limit["status"] == "awaiting_confirmation", limit
    assert limit["confirmation"]["details"]["single_limit_minor"] == 100_000
    assert confirm(client, limit).json()["status"] == "completed"

    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None
        initial_balance = session.get(Account, card.account_id).balance_minor
        assert card.single_limit_minor == 100_000

    purchase = submit(client, "用尾号1042的卡购买模拟鲜花", key="purchase-flowers")
    assert purchase["status"] == "awaiting_confirmation", purchase
    assert purchase["confirmation"]["details"]["amount_minor"] == 29_900
    actor[0] = DEMO_USER_TWO_ID
    assert confirm(client, purchase).status_code == 404
    actor[0] = DEMO_USER_ONE_ID
    result = confirm(client, purchase)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    assert confirm(client, purchase).status_code == 200
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        account = session.get(Account, card.account_id)
        assert account.balance_minor == initial_balance - 29_900
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.card_id == card.id,
                    Transaction.merchant == "模拟鲜花",
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.event_type == "card.purchase_executed",
                    AuditEvent.card_id == card.id,
                )
            )
            == 1
        )


def test_disabled_online_purchase_does_not_debit(shared_api_context) -> None:
    client, _actor, database = shared_api_context
    control = submit(client, "关闭尾号1042的卡线上支付", key="disable-online")
    assert control["status"] == "awaiting_confirmation", control
    assert confirm(client, control).status_code == 200
    purchase = submit(client, "用尾号1042的卡购买模拟蛋糕", key="blocked-cake")
    assert purchase["status"] != "awaiting_confirmation"
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.card_id == ALICE_ACTIVE_CARD_ID,
                    Transaction.merchant == "模拟蛋糕",
                )
            )
            == 0
        )


def test_card_control_version_conflict_rejects_stale_confirmation(shared_api_context) -> None:
    client, _actor, database = shared_api_context
    task = submit(client, "把尾号1042的卡单笔限额改成100元", key="stale-card-control")
    assert task["status"] == "awaiting_confirmation", task
    with database.session_factory.begin() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        card.label = "Updated by another operation"
    result = confirm(client, task)
    assert result.status_code == 409, result.text
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card.single_limit_minor == 50_000


def test_card_purchase_enforces_daily_limit_and_unchanged_balance(shared_api_context) -> None:
    client, _actor, database = shared_api_context
    for number in range(3):
        task = submit(
            client,
            "用尾号1042的卡购买模拟鲜花",
            key=f"daily-flowers-{number}",
        )
        assert task["status"] == "awaiting_confirmation", task
        assert confirm(client, task).status_code == 200
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        balance = session.get(Account, card.account_id).balance_minor
    blocked = submit(client, "用尾号1042的卡购买模拟鲜花", key="daily-flowers-blocked")
    assert blocked["status"] != "awaiting_confirmation"
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert session.get(Account, card.account_id).balance_minor == balance
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.card_id == card.id,
                    Transaction.merchant == "模拟鲜花",
                )
            )
            == 3
        )


def test_card_purchase_insufficient_funds_rejects_and_rolls_back(shared_api_context) -> None:
    client, _actor, database = shared_api_context
    task = submit(client, "用尾号1042的卡购买模拟蛋糕", key="cake-no-funds")
    assert task["status"] == "awaiting_confirmation", task
    with database.session_factory.begin() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        session.get(Account, card.account_id).balance_minor = 0
    result = confirm(client, task)
    assert result.status_code == 409, result.text
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert session.get(Account, card.account_id).balance_minor == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.card_id == card.id,
                    Transaction.merchant == "模拟蛋糕",
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.event_type == "card.purchase_executed",
                )
            )
            == 0
        )


def test_major_daily_limit_increase_requires_demo_otp(shared_api_context) -> None:
    client, _actor, database = shared_api_context
    task = submit(client, "把尾号1042的卡单日限额改成3000元", key="daily-high-limit")
    assert task["status"] == "awaiting_confirmation", task
    assert task["confirmation"]["confirmation_method"] == "demo_otp"
    assert confirm(client, task).status_code == 409
    with database.session_factory() as session:
        assert session.get(Card, ALICE_ACTIVE_CARD_ID).daily_limit_minor == 100_000
        with write_transaction(session, immediate=True):
            _, code = issue_demo_code(
                session,
                actor_id=DEMO_USER_ONE_ID,
                confirmation_id=UUID(task["confirmation"]["id"]),
                now=utc_now(),
            )
    challenge = task["confirmation"]
    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json={
            "challenge_id": challenge["id"],
            "parameters_hash": challenge["parameters_hash"],
            "verification_code": code,
        },
        headers={"Idempotency-Key": challenge["idempotency_key"]},
    )
    assert response.status_code == 200, response.text
    with database.session_factory() as session:
        assert session.get(Card, ALICE_ACTIVE_CARD_ID).daily_limit_minor == 300_000


def test_reduced_single_limit_blocks_purchase_and_audits_actual_control_change(
    shared_api_context,
) -> None:
    client, _actor, database = shared_api_context
    control = submit(
        client,
        "把尾号1042的卡单笔限额改成200元",
        key="single-limit-200",
    )
    assert control["status"] == "awaiting_confirmation", control
    assert confirm(client, control).status_code == 200

    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None
        assert card.single_limit_minor == 20_000
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.card_id == card.id,
                AuditEvent.event_type == "card.controls_changed",
            )
        )
        assert audit is not None
        assert audit.before_state == {
            "single_limit_minor": 50_000,
            "daily_limit_minor": 100_000,
            "online_enabled": True,
        }
        assert audit.after_state == {
            "single_limit_minor": 20_000,
            "daily_limit_minor": 100_000,
            "online_enabled": True,
        }
        balance = session.get(Account, card.account_id).balance_minor

    blocked = submit(client, "用尾号1042的卡购买模拟鲜花", key="blocked-single-limit")
    assert blocked["status"] != "awaiting_confirmation", blocked
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert session.get(Account, card.account_id).balance_minor == balance
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.card_id == card.id, Transaction.merchant == "模拟鲜花")
            )
            == 0
        )


def test_wrong_otp_does_not_change_limits_and_valid_retry_is_idempotent(shared_api_context) -> None:
    client, _actor, database = shared_api_context
    task = submit(client, "把尾号1042的卡单日限额改成3000元", key="otp-limit-retry")
    challenge = task["confirmation"]
    with database.session_factory() as session:
        with write_transaction(session, immediate=True):
            _, code = issue_demo_code(
                session,
                actor_id=DEMO_USER_ONE_ID,
                confirmation_id=UUID(challenge["id"]),
                now=utc_now(),
            )

    wrong_code = "000000" if code != "000000" else "000001"
    payload = {
        "challenge_id": challenge["id"],
        "parameters_hash": challenge["parameters_hash"],
        "verification_code": wrong_code,
    }
    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json=payload,
        headers={"Idempotency-Key": challenge["idempotency_key"]},
    )
    assert response.status_code == 409, response.text
    with database.session_factory() as session:
        assert session.get(Card, ALICE_ACTIVE_CARD_ID).daily_limit_minor == 100_000
        record = session.scalar(
            select(StrongVerification).where(
                StrongVerification.confirmation_id == UUID(challenge["id"])
            )
        )
        assert record is not None
        assert record.attempts == 1
        assert record.status == "pending"

    payload["verification_code"] = code
    accepted = client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json=payload,
        headers={"Idempotency-Key": challenge["idempotency_key"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "completed"
    replay = client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json=payload,
        headers={"Idempotency-Key": challenge["idempotency_key"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "completed"
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card.daily_limit_minor == 300_000
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.card_id == card.id,
                    AuditEvent.event_type == "card.controls_changed",
                )
            )
            == 1
        )
        record = session.scalar(
            select(StrongVerification).where(
                StrongVerification.confirmation_id == UUID(challenge["id"])
            )
        )
        assert record is not None and record.status == "consumed"


def test_concurrent_card_purchases_cannot_exceed_daily_limit(shared_api_context) -> None:
    client, _actor, database = shared_api_context
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        initial_balance = session.get(Account, card.account_id).balance_minor
    control = submit(client, "把尾号1042的卡单日限额改成500元", key="daily-limit-500")
    assert control["status"] == "awaiting_confirmation", control
    assert confirm(client, control).status_code == 200

    tasks = [
        submit(client, "用尾号1042的卡购买模拟鲜花", key=f"concurrent-flower-{index}")
        for index in range(2)
    ]
    assert all(task["status"] == "awaiting_confirmation" for task in tasks)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda task: confirm(client, task), tasks))

    assert sorted(response.status_code for response in responses) == [200, 409], [
        response.text for response in responses
    ]
    successful = next(response.json() for response in responses if response.status_code == 200)
    rejected = next(response.json() for response in responses if response.status_code == 409)
    assert successful["status"] == "completed"
    assert rejected["error"]["code"] == "card_version_conflict"

    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        account = session.get(Account, card.account_id)
        assert account.balance_minor == initial_balance - 29_900
        assert card.daily_limit_minor == 50_000
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.card_id == card.id, Transaction.merchant == "模拟鲜花")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.card_id == card.id,
                    AuditEvent.event_type == "card.purchase_executed",
                )
            )
            == 1
        )


def test_concurrent_duplicate_purchase_confirmation_has_one_ledger_effect(
    shared_api_context,
) -> None:
    client, _actor, database = shared_api_context
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        initial_balance = session.get(Account, card.account_id).balance_minor

    task = submit(client, "用尾号1042的卡购买模拟鲜花", key="same-purchase-confirmation")
    assert task["status"] == "awaiting_confirmation", task
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: confirm(client, task), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    assert all(response.json()["status"] in {"completed", "running"} for response in responses), [
        response.text for response in responses
    ]
    final_task = client.get(f"/api/v1/agent/tasks/{task['id']}")
    assert final_task.status_code == 200, final_task.text
    assert final_task.json()["status"] == "completed", final_task.text
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        account = session.get(Account, card.account_id)
        assert account.balance_minor == initial_balance - 29_900
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.card_id == card.id, Transaction.merchant == "模拟鲜花")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.card_id == card.id,
                    AuditEvent.event_type == "card.purchase_executed",
                )
            )
            == 1
        )
