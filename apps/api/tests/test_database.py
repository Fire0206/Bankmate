from finorch_api.infrastructure.models import Account, AuditEvent, Card, DemoUser
from finorch_api.seed_data import DATASET_VERSION, seed_demo_data
from sqlalchemy import func, inspect, select, text


def test_migration_creates_banking_tables_and_revision(database) -> None:
    table_names = set(inspect(database.engine).get_table_names())

    assert {"demo_users", "accounts", "cards", "audit_events"} <= table_names
    with database.engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "0001_banking_core"
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
