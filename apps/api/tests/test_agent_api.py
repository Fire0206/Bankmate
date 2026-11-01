from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID

import pytest
from bankmate_api.agent.providers import ProviderSelection
from bankmate_api.agent.runtime import (
    AgentProviderError,
    FakeProvider,
    LLMProvider,
    ModelToolCall,
    ModelTurn,
)
from bankmate_api.api.v1.agent import get_provider_selection
from bankmate_api.application.card_applications import review_card_application
from bankmate_api.application.errors import BankingRuleError
from bankmate_api.application.transactions import write_transaction
from bankmate_api.domain.cards import CardStatus
from bankmate_api.infrastructure.database import get_db_session
from bankmate_api.infrastructure.models import (
    AgentTask,
    AuditEvent,
    Card,
    CardApplication,
    ConfirmationChallenge,
    SplitBill,
    ToolExecution,
    utc_now,
)
from bankmate_api.main import app
from bankmate_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DEMO_USER_TWO_ID,
    DemoActor,
    get_current_demo_actor,
)
from bankmate_api.security.verification import issue_demo_code
from fastapi.testclient import TestClient
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select, update

ALICE_ACTIVE_CARD_ID = UUID("20000000-0000-4000-8000-000000000001")
ALICE_FROZEN_CARD_ID = UUID("20000000-0000-4000-8000-000000000002")
BOB_CARD_ID = UUID("20000000-0000-4000-8000-000000000003")
CONVERSATION_ID = "30000000-0000-4000-8000-000000000001"


@pytest.fixture
def api_context(seeded_database):
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


def submit(
    client: TestClient,
    text: str,
    key: str = "task-create-001",
    conversation_id: str = CONVERSATION_ID,
) -> dict:
    response = client.post(
        "/api/v1/agent/tasks",
        json={"request_text": text, "conversation_id": conversation_id},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client: TestClient, task: dict, *, key: str | None = None, digest: str | None = None):
    challenge = task["confirmation"]
    return client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json={
            "challenge_id": challenge["id"],
            "parameters_hash": digest or challenge["parameters_hash"],
        },
        headers={"Idempotency-Key": key or challenge["idempotency_key"]},
    )


def test_lost_card_replacement_is_confirmed_owned_and_idempotent(api_context) -> None:
    client, actor, database = api_context
    with database.session_factory.begin() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None
        card.status = CardStatus.LOST

    task = submit(client, "为尾号 1042 的已挂失银行卡申请模拟补卡", key="replace-proposal")
    assert task["status"] == "awaiting_confirmation", task
    challenge = task["confirmation"]
    assert challenge["tool_name"] == "card.replace"
    assert challenge["confirmation_method"] == "demo_otp"
    assert confirm(client, task).status_code == 409
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Card)) == 3
        with write_transaction(session, immediate=True):
            _, code = issue_demo_code(
                session,
                actor_id=DEMO_USER_ONE_ID,
                confirmation_id=UUID(challenge["id"]),
                now=utc_now(),
            )

    actor[0] = DEMO_USER_TWO_ID
    assert confirm(client, task).status_code == 404
    actor[0] = DEMO_USER_ONE_ID
    payload = {
        "challenge_id": challenge["id"],
        "parameters_hash": challenge["parameters_hash"],
        "verification_code": code,
    }
    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json=payload,
        headers={"Idempotency-Key": challenge["idempotency_key"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert confirm(client, task).status_code == 200
    with database.session_factory() as session:
        old = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert old is not None and old.status is CardStatus.REPLACED
        assert old.replaced_by_card_id is not None
        new = session.get(Card, old.replaced_by_card_id)
        assert new is not None and new.status is CardStatus.ACTIVE
        assert new.account_id == old.account_id and new.card_suffix != old.card_suffix
        assert session.scalar(select(func.count()).select_from(Card)) == 4
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.event_type == "card.replaced",
                    AuditEvent.card_id == old.id,
                )
            )
            == 1
        )
    unfreeze = submit(client, "解冻尾号 1042 的银行卡", key="unfreeze-replaced")
    assert unfreeze["status"] != "awaiting_confirmation"


def test_synthetic_card_application_requires_confirmation_and_local_review(api_context) -> None:
    client, actor, database = api_context
    task = submit(client, "为我的日常账户申请一张模拟借记卡", key="card-application-proposal")
    assert task["status"] == "awaiting_confirmation", task
    challenge = task["confirmation"]
    assert challenge["resource_type"] == "card_application"
    assert challenge["tool_name"] == "card.apply"
    assert challenge["confirmation_method"] == "explicit"
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Card)) == 3
        application = session.scalar(
            select(CardApplication).where(CardApplication.actor_id == actor[0])
        )
        assert application is not None and application.status == "pending_confirmation"
        application_id = application.id
    assert client.get("/api/v1/cards/applications").json()["items"] == []
    actor[0] = DEMO_USER_TWO_ID
    assert confirm(client, task).status_code == 404
    assert client.get("/api/v1/cards/applications").json()["items"] == []
    actor[0] = DEMO_USER_ONE_ID
    response = confirm(client, task)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert confirm(client, task).status_code == 200
    duplicate = submit(
        client, "为我的日常账户再申请一张模拟借记卡", key="duplicate-card-application"
    )
    assert duplicate["status"] != "awaiting_confirmation"
    with database.session_factory() as session:
        application = session.get(CardApplication, application_id)
        assert application is not None and application.status == "submitted"
        assert session.scalar(select(func.count()).select_from(Card)) == 3
        reviewed = review_card_application(session, application_id=application_id, approve=True)
        assert reviewed.status == "approved" and reviewed.issued_card_suffix is not None
        with pytest.raises(BankingRuleError):
            review_card_application(session, application_id=application_id, approve=True)
    with database.session_factory() as session:
        application = session.get(CardApplication, application_id)
        assert application is not None and application.issued_card_id is not None
        issued = session.get(Card, application.issued_card_id)
        assert issued is not None and issued.status is CardStatus.ACTIVE
        assert session.scalar(select(func.count()).select_from(Card)) == 4
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.event_type == "card.application_reviewed",
                    AuditEvent.resource_id == application_id,
                )
            )
            == 1
        )
    listed = client.get("/api/v1/cards/applications")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["status"] == "approved"
    queried = submit(client, "查询我的银行卡申请状态", key="card-application-status")
    assert queried["status"] == "completed"
    assert any(step["tool_name"] == "card.applications" for step in queried["steps"])


def test_competing_card_applications_cannot_both_be_submitted(api_context) -> None:
    client, _actor, database = api_context
    first = submit(
        client,
        "为我的日常账户申请一张模拟借记卡",
        key="card-application-first",
        conversation_id="40000000-0000-4000-8000-000000000001",
    )
    second = submit(
        client,
        "为我的日常账户申请一张模拟借记卡",
        key="card-application-second",
        conversation_id="40000000-0000-4000-8000-000000000002",
    )
    assert first["status"] == second["status"] == "awaiting_confirmation"
    assert confirm(client, first).status_code == 200
    stale = confirm(client, second)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "card_application_exists"
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CardApplication)
                .where(CardApplication.status == "submitted")
            )
            == 1
        )
        assert session.scalar(select(func.count()).select_from(Card)) == 3


def test_cancelled_card_application_stays_unissued_and_hidden(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "为我的日常账户申请一张模拟借记卡", key="cancel-card-application")
    assert task["status"] == "awaiting_confirmation"
    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/cancel",
        headers={"Idempotency-Key": "cancel-card-application-key"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert client.get("/api/v1/cards/applications").json()["items"] == []
    with database.session_factory() as session:
        application = session.scalar(select(CardApplication))
        assert application is not None and application.status == "cancelled"
        assert session.scalar(select(func.count()).select_from(Card)) == 3


def test_local_card_application_rejection_never_issues_card(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "为我的储蓄账户申请一张模拟借记卡", key="reject-card-application")
    assert task["status"] == "awaiting_confirmation"
    assert confirm(client, task).status_code == 200
    with database.session_factory() as session:
        application = session.scalar(select(CardApplication))
        assert application is not None
        reviewed = review_card_application(session, application_id=application.id, approve=False)
        assert reviewed.status == "rejected" and reviewed.issued_card_id is None
        assert session.scalar(select(func.count()).select_from(Card)) == 3
    listed = client.get("/api/v1/cards/applications")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["status"] == "rejected"


def test_fake_provider_lists_real_owned_cards_and_persists_task(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "查看我的银行卡")

    assert task["provider_mode"] == "fake"
    assert task["status"] == "completed"
    tool_step = next(step for step in task["steps"] if step["tool_name"] == "card.list")
    assert tool_step["status"] == "succeeded"
    assert {item["card_suffix"] for item in tool_step["result_data"]["items"]} == {"1042", "4318"}
    with database.session_factory() as session:
        persisted = session.get(AgentTask, UUID(task["id"]))
        assert persisted is not None and persisted.status == "completed"


def test_fake_provider_reads_one_owned_card_status(api_context) -> None:
    client, _actor, _database = api_context
    task = submit(client, "查看尾号 1042 的卡状态", key="read-card-status")

    assert task["status"] == "completed"
    card_step = next(step for step in task["steps"] if step["tool_name"] == "card.get")
    assert card_step["status"] == "succeeded"
    assert card_step["result_data"]["card_suffix"] == "1042"
    assert card_step["result_data"]["status"] == "active"


def test_report_lost_requires_confirmation_and_demo_verification(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "挂失尾号 1042 的银行卡", key="card-lost-proposal")
    assert task["status"] == "awaiting_confirmation", task
    challenge = task["confirmation"]
    assert challenge["tool_name"] == "card.report_lost"
    assert challenge["risk_level"] == "red"
    assert challenge["confirmation_method"] == "demo_otp"
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None and card.status is CardStatus.ACTIVE

    blocked = confirm(client, task)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "strong_verification_required"
    with database.session_factory() as session:
        with write_transaction(session, immediate=True):
            _, code = issue_demo_code(
                session,
                actor_id=DEMO_USER_ONE_ID,
                confirmation_id=UUID(challenge["id"]),
                now=utc_now(),
            )
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
    assert confirm(client, task).status_code == 200
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None and card.status is CardStatus.LOST and card.version == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.event_type == "card.status_changed",
                    AuditEvent.card_id == ALICE_ACTIVE_CARD_ID,
                )
            )
            == 1
        )

    unfreeze = submit(client, "解冻尾号 1042 的卡", key="lost-card-unfreeze-denied")
    assert unfreeze["status"] == "failed"
    with database.session_factory() as session:
        assert session.get(Card, ALICE_ACTIVE_CARD_ID).status is CardStatus.LOST


def test_report_lost_rejects_foreign_card(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "挂失尾号 2729 的银行卡", key="foreign-card-lost-denied")
    assert task["status"] == "failed"
    with database.session_factory() as session:
        assert session.get(Card, BOB_CARD_ID).status is CardStatus.ACTIVE


def test_fake_provider_does_not_read_another_users_card(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "查看尾号 2729 的卡状态", key="read-foreign-card")

    assert task["status"] == "failed"
    assert task["error_code"] == "card_not_found"
    with database.session_factory() as session:
        card = session.get(Card, BOB_CARD_ID)
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 1


def test_freeze_requires_confirmation_and_confirmation_commits_audit_atomically(
    api_context,
) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡")

    assert task["status"] == "awaiting_confirmation"
    assert task["confirmation"]["target_status"] == "frozen"
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "card.status_changed")
            )
            == 0
        )

    response = confirm(client, task)
    assert response.status_code == 200, response.text
    completed = response.json()
    assert completed["status"] == "completed"
    assert completed["confirmation"] is None
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None and card.status is CardStatus.FROZEN and card.version == 2
        status_event = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "card.status_changed")
        )
        assert status_event is not None
        assert status_event.task_id == UUID(task["id"])
        assert status_event.tool_execution_id is not None
        assert status_event.before_state == {"status": "active", "version": 1}
        assert status_event.after_state == {"status": "frozen", "version": 2}
        challenge = session.get(ConfirmationChallenge, UUID(task["confirmation"]["id"]))
        assert challenge is not None and challenge.status == "consumed"
        execution = session.scalar(
            select(ToolExecution).where(ToolExecution.task_id == UUID(task["id"]))
        )
        assert execution is not None and execution.status == "succeeded"

    audit_response = client.get(f"/api/v1/agent/tasks/{task['id']}/audit")
    assert audit_response.status_code == 200
    event_types = {event["event_type"] for event in audit_response.json()["events"]}
    assert {
        "agent.task_created",
        "card.confirmation_requested",
        "card.status_changed",
    } <= event_types


def test_unfreeze_and_repeated_confirmation_are_idempotent(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "解冻尾号 4318 的卡")
    assert task["status"] == "awaiting_confirmation"

    first = confirm(client, task)
    second = confirm(client, task)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "completed"
    with database.session_factory() as session:
        card = session.get(Card, ALICE_FROZEN_CARD_ID)
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "card.status_changed")
            )
            == 1
        )


def test_phase2f_reverse_card_instruction_executes_unfreeze_and_audits_actual_state(
    api_context,
) -> None:
    client, _actor, database = api_context
    task = submit(client, "解除尾号4318储蓄卡的冻结状态。", key="phase2f-unfreeze")

    assert task["status"] == "awaiting_confirmation"
    tool_names = [step["tool_name"] for step in task["steps"]]
    assert "card.unfreeze" in tool_names
    assert "card.freeze" not in tool_names
    assert task["confirmation"]["target_status"] == "active"

    response = confirm(client, task)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    refreshed = client.get(f"/api/v1/agent/tasks/{task['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "completed"
    with database.session_factory() as session:
        card = session.get(Card, ALICE_FROZEN_CARD_ID)
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "card.status_changed")
        )
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 2
        assert event is not None and event.after_state == {"status": "active", "version": 2}


def test_phase2f_ambiguous_card_is_clarified_before_any_write(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号1042或4318的卡", key="phase2f-ambiguous-card")

    assert task["status"] == "awaiting_input"
    assert task["confirmation"] is None
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ConfirmationChallenge)) == 0

    clarified = client.post(
        f"/api/v1/agent/tasks/{task['id']}/input",
        json={"request_text": "请冻结尾号1042的卡"},
        headers={"Idempotency-Key": "phase2f-card-clarification"},
    )
    assert clarified.status_code == 200, clarified.text
    proposal = clarified.json()
    assert proposal["status"] == "awaiting_confirmation"
    assert proposal["confirmation"]["card_suffix"] == "1042"
    assert "4318" not in str(proposal["confirmation"])

    confirmed = confirm(client, proposal)
    assert confirmed.status_code == 200, confirmed.text
    with database.session_factory() as session:
        active_card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        frozen_card = session.get(Card, ALICE_FROZEN_CARD_ID)
        assert active_card is not None and active_card.status is CardStatus.FROZEN
        assert (
            frozen_card is not None
            and frozen_card.status is CardStatus.FROZEN
            and frozen_card.version == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "card.status_changed")
            )
            == 1
        )


def test_phase2f_read_only_preflight_requests_call_history_and_products_tools(api_context) -> None:
    client, _actor, _database = api_context
    history = submit(
        client,
        "最近的转账和预约付款各是什么状态？",
        key="phase2f-history-preflight",
    )
    products = submit(
        client,
        "哪些模拟理财产品符合我的风险承受级别？",
        key="phase2f-products-preflight",
    )

    assert history["status"] == "completed"
    assert [step["tool_name"] for step in history["steps"] if step["tool_name"] is not None] == [
        "transfer.history"
    ]
    assert products["status"] == "completed"
    assert [step["tool_name"] for step in products["steps"] if step["tool_name"] is not None] == [
        "investment.products"
    ]


def test_phase2f_split_supplement_resumes_with_provided_fields(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "创建AA分账", key="phase2f-split-incomplete")
    assert task["status"] == "awaiting_input"
    assert task["confirmation"] is None

    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/input",
        json={"request_text": "活动名为团队聚餐，总额300元，参与人包括小林和小王。"},
        headers={"Idempotency-Key": "phase2f-split-supplement"},
    )
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["status"] == "awaiting_confirmation"
    assert proposal["confirmation"]["resource_label"] == "团队聚餐"
    assert proposal["confirmation"]["details"]["total_amount_minor"] == 30_000
    assert [item["display_name"] for item in proposal["confirmation"]["details"]["participants"]][
        -2:
    ] == ["小林", "小王"]

    completed = confirm(client, proposal)
    assert completed.status_code == 200, completed.text
    with database.session_factory() as session:
        split = session.scalar(select(SplitBill))
        assert split is not None and split.title == "团队聚餐"
        assert split.total_amount_minor == 30_000


def test_fake_provider_resolves_recent_card_from_conversation_context(api_context) -> None:
    client, _actor, _database = api_context
    frozen = submit(client, "冻结尾号 1042 的卡", key="context-freeze")
    assert confirm(client, frozen).status_code == 200

    unfreeze = submit(
        client,
        "把刚才冻结的卡解冻",
        key="context-unfreeze",
    )

    assert unfreeze["status"] == "awaiting_confirmation"
    assert unfreeze["confirmation"]["card_suffix"] == "1042"
    assert unfreeze["confirmation"]["target_status"] == "active"


def test_mismatched_confirmation_parameters_invalidate_challenge(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡")
    response = confirm(client, task, digest="0" * 64)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "confirmation_invalidated"
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        challenge = session.get(ConfirmationChallenge, UUID(task["confirmation"]["id"]))
        persisted_task = session.get(AgentTask, UUID(task["id"]))
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 1
        assert challenge is not None and challenge.status == "invalidated"
        assert persisted_task is not None and persisted_task.status == "failed"
        assert persisted_task.error_code == "confirmation_parameters_mismatch"


def test_expired_challenge_is_rejected_without_card_change(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡")
    challenge_id = UUID(task["confirmation"]["id"])
    with database.session_factory.begin() as session:
        session.execute(
            update(ConfirmationChallenge)
            .where(ConfirmationChallenge.id == challenge_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    response = confirm(client, task)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "confirmation_expired"
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        challenge = session.get(ConfirmationChallenge, challenge_id)
        assert card is not None and card.status is CardStatus.ACTIVE
        assert challenge is not None and challenge.status == "expired"


def test_foreign_card_suffix_fails_without_leaking_other_users_card(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 2729 的卡")

    assert task["status"] == "failed"
    assert task["error_code"] == "card_not_found"
    with database.session_factory() as session:
        card = session.get(Card, BOB_CARD_ID)
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 1
        assert session.scalar(select(func.count()).select_from(ConfirmationChallenge)) == 0


def test_ambiguous_request_can_be_clarified(api_context) -> None:
    client, _actor, _database = api_context
    task = submit(client, "冻结我的卡")
    assert task["status"] == "awaiting_input"
    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/input",
        json={"request_text": "冻结尾号 1042 的卡"},
        headers={"Idempotency-Key": "clarification-001"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "awaiting_confirmation"
    assert response.json()["confirmation"]["card_suffix"] == "1042"


def test_revised_input_cancels_old_confirmation_challenge(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡")
    old_challenge_id = UUID(task["confirmation"]["id"])
    revised = client.post(
        f"/api/v1/agent/tasks/{task['id']}/input",
        json={"request_text": "解冻尾号 4318 的卡"},
        headers={"Idempotency-Key": "revise-001"},
    )

    assert revised.status_code == 200, revised.text
    assert revised.json()["status"] == "awaiting_confirmation"
    assert revised.json()["confirmation"]["card_suffix"] == "4318"
    with database.session_factory() as session:
        old_challenge = session.get(ConfirmationChallenge, old_challenge_id)
        assert old_challenge is not None and old_challenge.status == "cancelled"
    old_confirmation = confirm(client, task)
    assert old_confirmation.status_code == 409
    assert old_confirmation.json()["error"]["code"] == "confirmation_not_pending"


def test_cancel_pending_operation_invalidates_challenge(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡")
    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/cancel",
        headers={"Idempotency-Key": "cancel-pending-operation"},
    )
    repeated = client.post(
        f"/api/v1/agent/tasks/{task['id']}/cancel",
        headers={"Idempotency-Key": "cancel-pending-operation"},
    )

    assert response.status_code == repeated.status_code == 200
    assert response.json()["status"] == repeated.json()["status"] == "cancelled"
    with database.session_factory() as session:
        challenge = session.get(ConfirmationChallenge, UUID(task["confirmation"]["id"]))
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert challenge is not None and challenge.status == "cancelled"
        assert card is not None and card.status is CardStatus.ACTIVE
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.task_id == UUID(task["id"]),
                    AuditEvent.event_type == "agent.task_cancelled",
                )
            )
            == 1
        )


def test_card_version_conflict_rejects_stale_challenge(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡")
    with database.session_factory.begin() as session:
        session.execute(
            update(Card).where(Card.id == ALICE_ACTIVE_CARD_ID).values(version=Card.version + 1)
        )

    response = confirm(client, task)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "card_version_conflict"
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 2


def test_confirm_database_failure_rolls_back_card_challenge_and_success_audit(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡")

    def fail_status_audit(_connection, _cursor, statement, _parameters, _context, _many) -> None:
        normalized = statement.lower().replace('"', "")
        if "insert into audit_events" in normalized and "card_id" in normalized:
            raise RuntimeError("simulated audit write failure")

    sqlalchemy_event.listen(database.engine, "before_cursor_execute", fail_status_audit)
    try:
        response = confirm(client, task)
    finally:
        sqlalchemy_event.remove(database.engine, "before_cursor_execute", fail_status_audit)

    assert response.status_code == 500
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        challenge = session.get(ConfirmationChallenge, UUID(task["confirmation"]["id"]))
        execution = session.scalar(
            select(ToolExecution).where(ToolExecution.task_id == UUID(task["id"]))
        )
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 1
        assert challenge is not None and challenge.status == "pending"
        assert execution is not None and execution.status == "awaiting_confirmation"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "card.status_changed")
            )
            == 0
        )


def test_same_idempotency_key_with_different_task_input_conflicts(api_context) -> None:
    client, _actor, _database = api_context
    submit(client, "查看我的银行卡", key="reused-key")
    response = client.post(
        "/api/v1/agent/tasks",
        json={
            "request_text": "冻结尾号 1042 的卡",
            "conversation_id": "30000000-0000-4000-8000-000000000001",
        },
        headers={"Idempotency-Key": "reused-key"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"


def test_task_resource_is_scoped_to_current_actor(api_context) -> None:
    client, actor, _database = api_context
    task = submit(client, "查看我的银行卡")
    actor[0] = DEMO_USER_TWO_ID
    response = client.get(f"/api/v1/agent/tasks/{task['id']}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_recent_task_restores_latest_actor_owned_task_including_completed(api_context) -> None:
    client, _actor, _database = api_context
    completed = submit(
        client,
        "查看我的银行卡",
        key="restore-completed",
        conversation_id="30000000-0000-4000-8000-000000000002",
    )
    pending = submit(client, "冻结尾号 1042 的卡", key="restore-pending")
    newer_completed = submit(
        client,
        "查看我的银行卡",
        key="restore-newer-completed",
        conversation_id=CONVERSATION_ID,
    )

    pending_response = client.get(
        "/api/v1/agent/tasks/recent",
        params={"conversation_id": pending["conversation_id"]},
    )

    assert pending_response.status_code == 200
    assert newer_completed["created_at"] > pending["created_at"]
    assert pending_response.json()["id"] == pending["id"]
    assert pending_response.json()["status"] == "awaiting_confirmation"
    assert pending_response.json()["steps"]
    assert pending_response.json()["confirmation"]["id"] == pending["confirmation"]["id"]

    completed_response = client.get(
        "/api/v1/agent/tasks/recent",
        params={"conversation_id": completed["conversation_id"]},
    )
    assert completed_response.status_code == 200
    assert completed_response.json()["id"] == completed["id"]
    assert completed_response.json()["status"] == "completed"


def test_task_history_lists_actor_owned_records_and_respects_limit(api_context) -> None:
    client, actor, _database = api_context
    older = submit(client, "查看我的银行卡", key="history-older")
    newer = submit(client, "查看我的账户余额", key="history-newer")

    full_history = client.get("/api/v1/agent/tasks/history", params={"limit": 20})
    assert full_history.status_code == 200
    assert {item["id"] for item in full_history.json()["items"]} == {
        older["id"],
        newer["id"],
    }

    response = client.get("/api/v1/agent/tasks/history", params={"limit": 1})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        full_history.json()["items"][0]["id"]
    ]

    actor[0] = DEMO_USER_TWO_ID
    foreign_history = client.get("/api/v1/agent/tasks/history")
    assert foreign_history.status_code == 200
    assert foreign_history.json()["items"] == []
    assert older["id"] != newer["id"]


def test_recent_and_idempotency_lookups_do_not_disclose_other_actors_tasks(api_context) -> None:
    client, actor, _database = api_context
    task = submit(client, "查看我的银行卡", key="private-lookup")
    actor[0] = DEMO_USER_TWO_ID

    recent = client.get(
        "/api/v1/agent/tasks/recent",
        params={"conversation_id": task["conversation_id"]},
    )
    by_key = client.get(
        "/api/v1/agent/tasks/by-idempotency-key/private-lookup",
        params={
            "conversation_id": task["conversation_id"],
            "operation": "create",
        },
    )

    assert recent.status_code == 200 and recent.json() is None
    assert by_key.status_code == 200 and by_key.json() is None


def test_idempotency_lookup_is_scoped_to_operation_and_task(api_context) -> None:
    client, _actor, _database = api_context
    created = submit(client, "查看我的银行卡", key="shared-scope-key")
    waiting = submit(client, "冻结我的卡", key="input-task-key")
    input_response = client.post(
        f"/api/v1/agent/tasks/{waiting['id']}/input",
        json={"request_text": "冻结尾号 1042 的卡"},
        headers={"Idempotency-Key": "shared-scope-key"},
    )
    assert input_response.status_code == 200

    create_lookup = client.get(
        "/api/v1/agent/tasks/by-idempotency-key/shared-scope-key",
        params={
            "conversation_id": created["conversation_id"],
            "operation": "create",
        },
    )
    input_lookup = client.get(
        "/api/v1/agent/tasks/by-idempotency-key/shared-scope-key",
        params={
            "conversation_id": waiting["conversation_id"],
            "operation": "input",
            "task_id": waiting["id"],
        },
    )

    assert create_lookup.status_code == 200
    assert create_lookup.json()["id"] == created["id"]
    assert input_lookup.status_code == 200
    assert input_lookup.json()["id"] == waiting["id"]
    assert input_lookup.json()["status"] == "awaiting_confirmation"


def test_idempotency_lookup_recovers_lost_confirmation_response_without_duplicate_effect(
    api_context,
) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡", key="lost-confirm-submit")
    challenge = task["confirmation"]

    class DropFirstConfirmationResponse:
        def __init__(self, wrapped_app) -> None:
            self.wrapped_app = wrapped_app
            self.drop_next_confirmation = True

        async def __call__(self, scope, receive, send) -> None:
            async def drop_confirmation_response(message) -> None:
                if (
                    self.drop_next_confirmation
                    and scope.get("type") == "http"
                    and scope.get("path", "").endswith("/confirm")
                    and message.get("type") == "http.response.start"
                ):
                    self.drop_next_confirmation = False
                    raise ConnectionError("simulated response loss after commit")
                await send(message)

            await self.wrapped_app(scope, receive, drop_confirmation_response)

    with TestClient(
        DropFirstConfirmationResponse(app), raise_server_exceptions=False
    ) as lossy_client:
        first_response = confirm(lossy_client, task)
        assert first_response.status_code == 500

        lookup = lossy_client.get(
            "/api/v1/agent/tasks/by-idempotency-key/" + challenge["idempotency_key"],
            params={
                "conversation_id": task["conversation_id"],
                "operation": "confirm",
                "task_id": task["id"],
            },
        )
        retry = confirm(lossy_client, task)

        assert lookup.status_code == 200
        assert lookup.json()["status"] == "completed"
        assert retry.status_code == 200
        assert retry.json()["id"] == task["id"]
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None and card.status is CardStatus.FROZEN and card.version == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "card.status_changed")
            )
            == 1
        )


def test_refreshing_task_after_confirmation_expiry_returns_persisted_failed_state(
    api_context,
) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡", key="expired-restore")
    challenge_id = UUID(task["confirmation"]["id"])
    with database.session_factory.begin() as session:
        challenge = session.get(ConfirmationChallenge, challenge_id)
        assert challenge is not None
        challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    restored = client.get(f"/api/v1/agent/tasks/{task['id']}")

    assert restored.status_code == 200
    assert restored.json()["status"] == "failed"
    assert restored.json()["error_code"] == "confirmation_expired"
    assert restored.json()["confirmation"] is None
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        challenge = session.get(ConfirmationChallenge, challenge_id)
        task_row = session.get(AgentTask, UUID(task["id"]))
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 1
        assert challenge is not None and challenge.status == "expired"
        assert task_row is not None and task_row.status == "failed"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "card.confirmation_expired")
            )
            == 1
        )


def test_concurrent_confirmation_has_one_business_effect(api_context) -> None:
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡")

    def do_confirm():
        return confirm(client, task)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _index: do_confirm(), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None and card.status is CardStatus.FROZEN and card.version == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "card.status_changed")
            )
            == 1
        )


def test_concurrent_task_creation_with_same_key_runs_provider_once(api_context) -> None:
    client, _actor, database = api_context
    task_text = "冻结尾号 1042 的卡"

    def do_submit():
        return client.post(
            "/api/v1/agent/tasks",
            json={
                "request_text": task_text,
                "conversation_id": "30000000-0000-4000-8000-000000000001",
            },
            headers={"Idempotency-Key": "concurrent-task-create"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _index: do_submit(), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    task_ids = {response.json()["id"] for response in responses}
    assert len(task_ids) == 1
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentTask)
                .where(AgentTask.id == UUID(next(iter(task_ids))))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ToolExecution)
                .where(ToolExecution.task_id == UUID(next(iter(task_ids))))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ConfirmationChallenge)
                .where(ConfirmationChallenge.task_id == UUID(next(iter(task_ids))))
            )
            == 1
        )


class UnknownToolProvider(FakeProvider):
    def complete(self, messages, tools):
        del messages, tools
        return ModelTurn(
            "",
            (ModelToolCall("unknown-1", "card.delete", "{}"),),
        )


def test_unknown_provider_tool_is_rejected_and_persisted(api_context):
    client, _actor, database = api_context
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        UnknownToolProvider(), "fake"
    )
    try:
        task = submit(client, "冻结尾号 1042 的卡", key="unknown-tool-task")
    finally:
        app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
            FakeProvider(), "fake"
        )

    assert task["status"] == "failed"
    assert task["error_code"] == "unknown_tool"
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        execution = session.scalar(
            select(ToolExecution).where(ToolExecution.task_id == UUID(task["id"]))
        )
        assert card is not None and card.status is CardStatus.ACTIVE
        assert execution is not None and execution.tool_name == "card.delete"
        assert execution.status == "failed"


def test_invalid_tool_schema_is_rejected_before_handler(api_context):
    client, _actor, database = api_context

    class InvalidArgumentsProvider(FakeProvider):
        def complete(self, messages, tools):
            del messages, tools
            return ModelTurn(
                "",
                (ModelToolCall("bad-1", "card.freeze", '{"card_suffix":"not-a-suffix"}'),),
            )

    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        InvalidArgumentsProvider(), "fake"
    )
    try:
        task = submit(client, "冻结尾号1042的卡", key="invalid-args-task")
    finally:
        app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
            FakeProvider(), "fake"
        )

    assert task["status"] == "awaiting_input"
    assert task["error_code"] is None
    assert task["steps"][-1]["error_code"] == "tool_input_invalid"
    with database.session_factory() as session:
        assert session.get(Card, ALICE_ACTIVE_CARD_ID).status is CardStatus.ACTIVE
        assert session.scalar(select(func.count()).select_from(ConfirmationChallenge)) == 0


def test_confirm_wrong_idempotency_key_conflicts_without_mutation(api_context):
    client, _actor, database = api_context
    task = submit(client, "冻结尾号 1042 的卡")
    response = confirm(client, task, key="different-idempotency-key")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    with database.session_factory() as session:
        assert session.get(Card, ALICE_ACTIVE_CARD_ID).status is CardStatus.ACTIVE
        assert (
            session.get(ConfirmationChallenge, UUID(task["confirmation"]["id"])).status == "pending"
        )


def test_unconfigured_real_provider_persists_failure_without_execution(api_context):
    client, _actor, database = api_context
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        None,
        "openai-compatible",
        AgentProviderError("provider_not_configured", "Missing model configuration."),
    )
    try:
        task = submit(client, "冻结尾号 1042 的卡", key="missing-provider-task")
    finally:
        app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
            FakeProvider(), "fake"
        )

    assert task["provider_mode"] == "openai-compatible"
    assert task["status"] == "failed"
    assert task["error_code"] == "provider_not_configured"
    handoff = client.get(f"/api/v1/agent/tasks/{task['id']}/handoff")
    assert handoff.status_code == 200, handoff.text
    assert handoff.json()["reason"] == "cannot_continue"
    with database.session_factory() as session:
        assert session.get(Card, ALICE_ACTIVE_CARD_ID).status is CardStatus.ACTIVE
        assert session.scalar(select(func.count()).select_from(ToolExecution)) == 0


def test_unexpected_provider_exception_is_persisted_as_failed_task(api_context):
    client, _actor, database = api_context

    class BrokenProvider(LLMProvider):
        mode = "openai-compatible"

        def complete(self, messages, tools):
            del messages, tools
            raise RuntimeError("provider internals must not be returned to the client")

    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        BrokenProvider(), "openai-compatible"
    )
    try:
        response = client.post(
            "/api/v1/agent/tasks",
            json={"request_text": "查看我的银行卡", "conversation_id": CONVERSATION_ID},
            headers={"Idempotency-Key": "unexpected-provider-error"},
        )
    finally:
        app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
            FakeProvider(), "fake"
        )

    assert response.status_code == 200, response.text
    task = response.json()
    assert task["status"] == "failed"
    assert task["error_code"] == "agent_runtime_error"
    assert task["steps"][0]["status"] == "failed"
    assert "provider internals" not in task["message"]
    with database.session_factory() as session:
        persisted = session.get(AgentTask, UUID(task["id"]))
        assert persisted is not None and persisted.status == "failed"
        assert session.get(Card, ALICE_ACTIVE_CARD_ID).status is CardStatus.ACTIVE


def test_cancellation_wins_over_a_late_provider_tool_call(api_context):
    client, _actor, database = api_context
    provider_started = Event()
    continue_provider = Event()

    class DelayedWriteProvider(LLMProvider):
        mode = "openai-compatible"

        def complete(self, messages, tools):
            del messages, tools
            provider_started.set()
            assert continue_provider.wait(timeout=10)
            return ModelTurn(
                "", (ModelToolCall("late-freeze", "card.freeze", '{"card_suffix":"1042"}'),)
            )

    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        DelayedWriteProvider(), "openai-compatible"
    )
    task_key = "cancel-before-late-tool"
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending_request = pool.submit(
                lambda: client.post(
                    "/api/v1/agent/tasks",
                    json={"request_text": "冻结尾号 1042 的卡", "conversation_id": CONVERSATION_ID},
                    headers={"Idempotency-Key": task_key},
                )
            )
            assert provider_started.wait(timeout=10)
            recent = client.get(
                f"/api/v1/agent/tasks/recent?conversation_id={CONVERSATION_ID}"
            ).json()
            cancel_response = client.post(
                f"/api/v1/agent/tasks/{recent['id']}/cancel",
                headers={"Idempotency-Key": "cancel-in-flight-task"},
            )
            assert cancel_response.status_code == 200, cancel_response.text
            assert cancel_response.json()["status"] == "cancelled"
            continue_provider.set()
            late_response = pending_request.result(timeout=10)
    finally:
        continue_provider.set()
        app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
            FakeProvider(), "fake"
        )

    assert late_response.status_code == 200, late_response.text
    task = late_response.json()
    assert task["status"] == "cancelled"
    assert task["error_code"] is None
    assert task["message"] == "任务已取消；尚未确认的操作没有执行。"
    assert task["confirmation"] is None
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 1
        assert session.scalar(select(func.count()).select_from(ConfirmationChallenge)) == 0
        assert session.scalar(select(func.count()).select_from(ToolExecution)) == 0


def test_provider_text_cannot_claim_card_change_without_registered_tool(api_context):
    client, _actor, database = api_context

    class ClaimingProvider(LLMProvider):
        mode = "openai-compatible"

        def complete(self, messages, tools):
            del messages, tools
            return ModelTurn("尾号 1042 的卡片已冻结。")

    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        ClaimingProvider(), "openai-compatible"
    )
    try:
        task = submit(client, "冻结尾号 1042 的卡", key="provider-text-no-tool")
    finally:
        app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
            FakeProvider(), "fake"
        )

    assert task["status"] == "awaiting_input"
    assert "没有执行操作" in task["message"]
    with database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 1
        assert session.scalar(select(func.count()).select_from(ToolExecution)) == 0
        assert session.scalar(select(func.count()).select_from(ConfirmationChallenge)) == 0


def test_agent_task_can_be_cancelled_while_waiting_for_input(api_context):
    client, _actor, _database = api_context
    task = submit(client, "冻结我的卡", key="cancel-input-task")
    assert task["status"] == "awaiting_input"
    response = client.post(
        f"/api/v1/agent/tasks/{task['id']}/cancel",
        headers={"Idempotency-Key": "cancel-input-task"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
