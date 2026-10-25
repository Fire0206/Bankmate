import sqlite3
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from finorch_api.application.cards import (
    CardNotFoundError,
    freeze_card,
    get_card,
    list_cards,
    unfreeze_card,
)
from finorch_api.application.transactions import write_transaction
from finorch_api.domain.cards import CardStatus, InvalidCardTransition
from finorch_api.infrastructure.models import (
    Account,
    AgentTask,
    AuditEvent,
    BirthdayPlan,
    Card,
    CardApplication,
    DemoUser,
    HumanHandoff,
)
from finorch_api.security.demo_identity import DEMO_USER_ONE_ID
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

ALICE_ACTIVE_CARD_ID = UUID("20000000-0000-4000-8000-000000000001")
ALICE_FROZEN_CARD_ID = UUID("20000000-0000-4000-8000-000000000002")
BOB_CARD_ID = UUID("20000000-0000-4000-8000-000000000003")


def test_application_lists_only_cards_owned_by_actor(seeded_database) -> None:
    with seeded_database.session_factory() as session:
        page = list_cards(session, actor_id=DEMO_USER_ONE_ID, limit=20)

    assert {card.id for card in page.items} == {ALICE_ACTIVE_CARD_ID, ALICE_FROZEN_CARD_ID}
    assert page.has_more is False


def test_application_hides_another_users_card(seeded_database) -> None:
    with seeded_database.session_factory() as session:
        with pytest.raises(CardNotFoundError):
            get_card(session, actor_id=DEMO_USER_ONE_ID, card_id=BOB_CARD_ID)


def test_active_card_can_be_frozen_and_audited(seeded_database) -> None:
    with seeded_database.session_factory() as session:
        result = freeze_card(
            session,
            actor_id=DEMO_USER_ONE_ID,
            card_id=ALICE_ACTIVE_CARD_ID,
            request_id="freeze-test-001",
        )

    assert result.status is CardStatus.FROZEN
    assert result.version == 2
    with seeded_database.session_factory() as session:
        audit = session.scalar(select(AuditEvent))
        assert audit is not None
        assert audit.actor_id == DEMO_USER_ONE_ID
        assert audit.card_id == ALICE_ACTIVE_CARD_ID
        assert audit.previous_status == "active"
        assert audit.new_status == "frozen"
        assert audit.resource_version == result.version
        assert audit.request_id == "freeze-test-001"


def test_read_then_write_starts_a_fresh_owned_transaction(seeded_database) -> None:
    with seeded_database.session_factory() as session:
        page = list_cards(session, actor_id=DEMO_USER_ONE_ID, limit=20)
        assert len(page.items) == 2
        updated = freeze_card(
            session,
            actor_id=DEMO_USER_ONE_ID,
            card_id=ALICE_ACTIVE_CARD_ID,
            request_id="read-then-write-001",
        )

    assert updated.status is CardStatus.FROZEN
    with seeded_database.session_factory() as session:
        assert session.get(Card, ALICE_ACTIVE_CARD_ID).status is CardStatus.FROZEN
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_explicit_application_uow_rolls_back_joined_card_write(seeded_database) -> None:
    with seeded_database.session_factory() as session:
        with pytest.raises(RuntimeError, match="force outer rollback"):
            with write_transaction(session):
                freeze_card(
                    session,
                    actor_id=DEMO_USER_ONE_ID,
                    card_id=ALICE_ACTIVE_CARD_ID,
                    request_id="outer-uow-rollback-001",
                )
                raise RuntimeError("force outer rollback")

    with seeded_database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None and card.status is CardStatus.ACTIVE and card.version == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_frozen_card_can_be_unfrozen(seeded_database) -> None:
    with seeded_database.session_factory() as session:
        result = unfreeze_card(
            session,
            actor_id=DEMO_USER_ONE_ID,
            card_id=ALICE_FROZEN_CARD_ID,
            request_id="unfreeze-test-001",
        )

    assert result.status is CardStatus.ACTIVE
    assert result.version == 2


@pytest.mark.parametrize(
    ("operation", "card_id"),
    [(unfreeze_card, ALICE_ACTIVE_CARD_ID), (freeze_card, ALICE_FROZEN_CARD_ID)],
)
def test_illegal_card_state_transition_is_rejected(seeded_database, operation, card_id) -> None:
    with seeded_database.session_factory() as session:
        with pytest.raises(InvalidCardTransition):
            operation(
                session,
                actor_id=DEMO_USER_ONE_ID,
                card_id=card_id,
                request_id="invalid-transition-001",
            )

    with seeded_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_database_failure_rolls_back_card_state_and_audit(seeded_database) -> None:
    def fail_audit_insert(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if "insert into audit_events" in statement.lower():
            raise sqlite3.OperationalError("simulated audit insert failure")

    event.listen(seeded_database.engine, "before_cursor_execute", fail_audit_insert)
    try:
        with seeded_database.session_factory() as session:
            with pytest.raises((OperationalError, sqlite3.OperationalError)):
                freeze_card(
                    session,
                    actor_id=DEMO_USER_ONE_ID,
                    card_id=ALICE_ACTIVE_CARD_ID,
                    request_id="rollback-test-001",
                )
    finally:
        event.remove(seeded_database.engine, "before_cursor_execute", fail_audit_insert)

    with seeded_database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None
        assert card.status is CardStatus.ACTIVE
        assert card.version == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_seed_reset_restores_demo_baseline_and_is_path_guarded(seeded_database) -> None:
    from finorch_api.reset import reset_demo_data, validate_reset_target

    repository_root = Path(__file__).resolve().parents[3]

    validate_reset_target(
        environment="test",
        database_url=seeded_database.url,
        repository_root=repository_root,
    )
    validate_reset_target(
        environment="development",
        database_url=f"sqlite:///{repository_root.as_posix()}/.data/finorch.db",
        repository_root=repository_root,
    )
    with pytest.raises(ValueError):
        validate_reset_target(
            environment="production",
            database_url=seeded_database.url,
            repository_root=repository_root,
        )
    with pytest.raises(ValueError):
        validate_reset_target(
            environment="development",
            database_url=seeded_database.url,
            repository_root=repository_root,
        )
    with pytest.raises(ValueError):
        validate_reset_target(
            environment="development",
            database_url=f"sqlite:///{repository_root.as_posix()}/.data/other.sqlite3",
            repository_root=repository_root,
        )
    with pytest.raises(ValueError):
        validate_reset_target(
            environment="test",
            database_url=f"sqlite:///{Path.home().as_posix()}/unrelated.sqlite3",
            repository_root=repository_root,
        )

    with seeded_database.session_factory() as session:
        freeze_card(
            session,
            actor_id=DEMO_USER_ONE_ID,
            card_id=ALICE_ACTIVE_CARD_ID,
            request_id="reset-test-001",
        )
    with seeded_database.session_factory.begin() as session:
        reset_demo_data(session)

    with seeded_database.session_factory() as session:
        card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        assert card is not None
        assert card.status is CardStatus.ACTIVE
        assert card.version == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_seed_reset_clears_card_and_workflow_records_before_parent_rows(seeded_database) -> None:
    from finorch_api.reset import reset_demo_data

    with seeded_database.session_factory.begin() as session:
        account = session.scalar(select(Account).where(Account.demo_user_id == DEMO_USER_ONE_ID))
        original_card = session.get(Card, ALICE_ACTIVE_CARD_ID)
        actor = session.get(DemoUser, DEMO_USER_ONE_ID)
        assert account is not None and original_card is not None and actor is not None

        replacement = Card(
            account_id=account.id,
            label="Synthetic replacement",
            card_suffix="9998",
            status=CardStatus.ACTIVE,
        )
        task = AgentTask(
            actor_id=actor.id,
            conversation_id=uuid4(),
            idempotency_key="reset-handoff-task",
            request_hash="a" * 64,
            request_text="Review synthetic card request",
            provider_mode="fake",
            status="failed",
            message="Synthetic test task",
        )
        session.add_all([replacement, task])
        session.flush()
        original_card.status = CardStatus.REPLACED
        original_card.replaced_by_card_id = replacement.id
        session.add_all(
            [
                CardApplication(
                    actor_id=actor.id,
                    account_id=account.id,
                    label="Synthetic replacement",
                    status="submitted",
                    issued_card_id=replacement.id,
                ),
                BirthdayPlan(
                    actor_id=actor.id,
                    account_id=account.id,
                    birthday_on=date(2000, 1, 1),
                    purchase_on=date(2026, 11, 1),
                    budget_minor=10_000,
                    catalog_total_minor=8_000,
                    status="scheduled",
                ),
                HumanHandoff(
                    actor_id=actor.id,
                    task_id=task.id,
                    status="pending",
                    reason="provider_failure",
                ),
            ]
        )

    with seeded_database.session_factory.begin() as session:
        reset_demo_data(session)

    with seeded_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CardApplication)) == 0
        assert session.scalar(select(func.count()).select_from(BirthdayPlan)) == 0
        assert session.scalar(select(func.count()).select_from(HumanHandoff)) == 0
        assert session.scalar(select(func.count()).select_from(DemoUser)) == 2
    with seeded_database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
