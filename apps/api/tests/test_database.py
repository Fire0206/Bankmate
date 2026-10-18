from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from finorch_api.infrastructure.database import build_engine
from finorch_api.infrastructure.models import Account, AuditEvent, Card, DemoUser
from finorch_api.seed_data import DATASET_VERSION, seed_demo_data
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_migration_creates_banking_tables_and_revision(database) -> None:
    table_names = set(inspect(database.engine).get_table_names())

    assert {
        "demo_users",
        "accounts",
        "cards",
        "audit_events",
        "agent_tasks",
        "task_steps",
        "tool_executions",
        "confirmation_challenges",
    } <= table_names
    with database.engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "0002_agent_workflow_and_audit"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_seed_is_repeatable_without_duplicate_rows(seeded_database) -> None:
    with seeded_database.session_factory.begin() as session:
        first_state = (
            session.scalar(select(func.count()).select_from(DemoUser)),
            session.scalar(select(func.count()).select_from(Account)),
            session.scalar(select(func.count()).select_from(Card)),
            session.scalar(select(func.count()).select_from(AuditEvent)),
            session.scalar(select(DemoUser.dataset_version).limit(1)),
        )
        assert first_state[4] == DATASET_VERSION

    with seeded_database.session_factory.begin() as session:
        seed_demo_data(session)
        second_state = (
            session.scalar(select(func.count()).select_from(DemoUser)),
            session.scalar(select(func.count()).select_from(Account)),
            session.scalar(select(func.count()).select_from(Card)),
            session.scalar(select(func.count()).select_from(AuditEvent)),
            session.scalar(select(DemoUser.dataset_version).limit(1)),
        )

    assert second_state == first_state == (2, 3, 3, 0, DATASET_VERSION)


def test_phase1a_card_audit_data_survives_generic_audit_migration(tmp_path: Path) -> None:
    path = tmp_path / "migration-history.sqlite3"
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    engine = build_engine(url)
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.attributes["database_url"] = url
    try:
        command.upgrade(config, "0001_banking_core")
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory.begin() as session:
            seed_demo_data(session)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_id, card_id, event_type, previous_status, new_status, "
                    "resource_version, request_id, occurred_at) "
                    "VALUES (:id, :actor_id, :card_id, 'card.status_changed', 'active', "
                    "'frozen', 2, 'legacy-request', '2026-10-18 00:00:00')"
                ),
                {
                    "id": "60000000000040008000000000000001",
                    "actor_id": "00000000000040008000000000000001",
                    "card_id": "20000000000040008000000000000001",
                },
            )

        command.upgrade(config, "head")
        with factory() as session:
            event = session.get(AuditEvent, UUID("60000000-0000-4000-8000-000000000001"))
            assert event is not None
            assert event.card_id == event.resource_id
            assert event.resource_type == "card"
            assert event.previous_status == "active"
            assert event.new_status == "frozen"
            assert event.outcome == "succeeded"
            assert event.request_id == "legacy-request"
    finally:
        engine.dispose()
