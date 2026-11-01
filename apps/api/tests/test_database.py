from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from bankmate_api.infrastructure.database import build_engine
from bankmate_api.infrastructure.models import (
    Account,
    AuditEvent,
    Card,
    DemoUser,
    InvestmentProduct,
    Payee,
    RiskAssessment,
    Subscription,
    Transaction,
)
from bankmate_api.seed_data import DATASET_VERSION, seed_demo_data

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_migration_creates_banking_tables_and_revision(database) -> None:
    table_names = set(inspect(database.engine).get_table_names())

    assert {
        "demo_users",
        "accounts",
        "cards",
        "transactions",
        "subscriptions",
        "audit_events",
        "agent_tasks",
        "task_steps",
        "tool_executions",
        "confirmation_challenges",
        "strong_verifications",
        "payees",
        "transfers",
        "split_bills",
        "split_participants",
        "investment_products",
        "investment_holdings",
        "investment_orders",
        "risk_assessments",
        "birthday_plans",
    } <= table_names
    assert "workflow_plan" in {
        column["name"] for column in inspect(database.engine).get_columns("agent_tasks")
    }
    with database.engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "0017_birthday_reservations_orders"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    assert "phone_number" in {
        column["name"] for column in inspect(database.engine).get_columns("payees")
    }
    assert "remark" in {
        column["name"] for column in inspect(database.engine).get_columns("transfers")
    }
    assert {"reminder_days_before", "last_reminded_charge_at"} <= {
        column["name"] for column in inspect(database.engine).get_columns("subscriptions")
    }


def test_workflow_plan_migration_preserves_existing_task(tmp_path: Path) -> None:
    path = tmp_path / "migration-workflow-plan.sqlite3"
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.attributes["database_url"] = url
    engine = build_engine(url)
    try:
        command.upgrade(config, "0015_birthday_plans")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO demo_users (id, display_name, dataset_version, created_at) "
                    "VALUES ('00000000000040008000000000000002', 'Workflow Demo', 'old', "
                    "'2026-10-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO agent_tasks (id, actor_id, conversation_id, idempotency_key, "
                    "request_hash, request_text, provider_mode, status, message, version, "
                    "created_at, updated_at) VALUES "
                    "('50000000000040008000000000000002', "
                    "'00000000000040008000000000000002', "
                    "'60000000000040008000000000000002', 'old-task', 'hash', '查看余额', "
                    "'fake', 'completed', 'done', 1, '2026-10-01', '2026-10-01')"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT request_text, workflow_plan FROM agent_tasks WHERE id = :task_id"),
                {"task_id": "50000000000040008000000000000002"},
            ).one()
            assert row.request_text == "查看余额"
            assert row.workflow_plan is None
    finally:
        engine.dispose()


def test_card_control_migration_preserves_existing_card_and_defaults(tmp_path: Path) -> None:
    path = tmp_path / "migration-card-controls.sqlite3"
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.attributes["database_url"] = url
    engine = build_engine(url)
    try:
        command.upgrade(config, "0013_card_applications")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO demo_users (id, display_name, dataset_version, created_at) "
                    "VALUES ('00000000000040008000000000000001', 'Prior Demo', 'old', '2026-10-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO accounts (id, demo_user_id, label, currency, "
                    "opening_balance_minor, created_at) VALUES "
                    "('10000000000040008000000000000001', "
                    "'00000000000040008000000000000001', 'Prior Account', 'CNY', "
                    "100000, '2026-10-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO cards (id, account_id, label, card_suffix, status, version, "
                    "created_at, updated_at) VALUES "
                    "('20000000000040008000000000000001', "
                    "'10000000000040008000000000000001', 'Prior Card', '9876', "
                    "'active', 1, '2026-10-01', '2026-10-01')"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT label, card_suffix, single_limit_minor, daily_limit_minor, "
                    "online_enabled FROM cards WHERE card_suffix='9876'"
                )
            ).one()
            assert row == ("Prior Card", "9876", 50_000, 100_000, 1)
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    finally:
        engine.dispose()


def test_birthday_migration_preserves_existing_synthetic_accounts(tmp_path: Path) -> None:
    path = tmp_path / "migration-birthday-plans.sqlite3"
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.attributes["database_url"] = url
    engine = build_engine(url)
    try:
        command.upgrade(config, "0014_card_controls")
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory.begin() as session:
            seed_demo_data(session)
        with engine.connect() as connection:
            before = connection.scalar(text("SELECT COUNT(*) FROM accounts"))
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM accounts")) == before
            assert connection.scalar(text("SELECT COUNT(*) FROM birthday_plans")) == 0
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0017_birthday_reservations_orders"
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
                        "AND name = 'birthday_orders'"
                    )
                )
                == 1
            )
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


def test_seed_is_repeatable_without_duplicate_rows(seeded_database) -> None:
    with seeded_database.session_factory.begin() as session:
        first_state = (
            session.scalar(select(func.count()).select_from(DemoUser)),
            session.scalar(select(func.count()).select_from(Account)),
            session.scalar(select(func.count()).select_from(Card)),
            session.scalar(select(func.count()).select_from(AuditEvent)),
            session.scalar(select(func.count()).select_from(Transaction)),
            session.scalar(select(func.count()).select_from(Subscription)),
            session.scalar(select(func.count()).select_from(Payee)),
            session.scalar(select(func.count()).select_from(InvestmentProduct)),
            session.scalar(select(DemoUser.dataset_version).limit(1)),
        )
        assert first_state[8] == DATASET_VERSION

    with seeded_database.session_factory.begin() as session:
        seed_demo_data(session)
        second_state = (
            session.scalar(select(func.count()).select_from(DemoUser)),
            session.scalar(select(func.count()).select_from(Account)),
            session.scalar(select(func.count()).select_from(Card)),
            session.scalar(select(func.count()).select_from(AuditEvent)),
            session.scalar(select(func.count()).select_from(Transaction)),
            session.scalar(select(func.count()).select_from(Subscription)),
            session.scalar(select(func.count()).select_from(Payee)),
            session.scalar(select(func.count()).select_from(InvestmentProduct)),
            session.scalar(select(DemoUser.dataset_version).limit(1)),
        )

    assert second_state == first_state == (2, 3, 3, 0, 31, 3, 3, 3, DATASET_VERSION)
    with seeded_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 0
        assert (
            session.scalar(select(Payee.phone_number).where(Payee.display_name == "储蓄账户"))
            is None
        )
        assert (
            session.scalar(
                select(Payee.phone_number).where(
                    Payee.id == UUID("30000000-0000-4000-8000-000000000001")
                )
            )
            == "19900001042"
        )
        seeded_bills = list(
            session.scalars(select(Transaction).where(Transaction.entry_kind == "bill"))
        )
        assert len(seeded_bills) == 31
        assert all(item.card_id is not None for item in seeded_bills)


def test_seed_updates_dataset_version_for_existing_demo_users(seeded_database) -> None:
    with seeded_database.session_factory.begin() as session:
        for user in session.scalars(select(DemoUser)):
            user.dataset_version = "phase1a-v1"

    with seeded_database.session_factory.begin() as session:
        seed_demo_data(session)
        versions = set(session.scalars(select(DemoUser.dataset_version)))

    assert versions == {DATASET_VERSION}


def test_transfer_phone_remark_migration_preserves_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "migration-transfer.sqlite3"
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.attributes["database_url"] = url
    engine = build_engine(url)
    try:
        command.upgrade(config, "0006_strong_verifications")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO demo_users (id, display_name, dataset_version, created_at) "
                    "VALUES ('00000000000040008000000000000001', 'Prior Demo', 'old', '2026-10-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO accounts (id, demo_user_id, label, currency, "
                    "opening_balance_minor, created_at) VALUES "
                    "('10000000000040008000000000000001', "
                    "'00000000000040008000000000000001', 'Prior Account', 'CNY', "
                    "100000, '2026-10-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO accounts (id, demo_user_id, label, currency, "
                    "opening_balance_minor, created_at) VALUES "
                    "('10000000000040008000000000000002', "
                    "'00000000000040008000000000000001', 'Prior Destination', 'CNY', "
                    "100000, '2026-10-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO payees (id, actor_id, destination_account_id, "
                    "display_name, normalized_name, created_at) VALUES "
                    "('30000000000040008000000000000001', "
                    "'00000000000040008000000000000001', "
                    "'10000000000040008000000000000002', 'Prior Payee', "
                    "'prior payee', '2026-10-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO transfers (id, actor_id, source_account_id, "
                    "destination_account_id, payee_id, payee_name, amount_minor, "
                    "currency, transfer_type, status, idempotency_key, version, "
                    "created_at, updated_at) VALUES "
                    "('50000000000040008000000000000001', "
                    "'00000000000040008000000000000001', "
                    "'10000000000040008000000000000001', "
                    "'10000000000040008000000000000002', "
                    "'30000000000040008000000000000001', 'Prior Payee', 1000, "
                    "'CNY', 'immediate', 'executed', 'prior-key', 1, "
                    "'2026-10-01', '2026-10-01')"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT display_name, phone_number FROM payees WHERE display_name='Prior Payee'"
                )
            ).one()
            assert row == ("Prior Payee", None)
            transfer = connection.execute(
                text(
                    "SELECT amount_minor, remark FROM transfers "
                    "WHERE id='50000000000040008000000000000001'"
                )
            ).one()
            assert transfer == (1000, None)
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0017_birthday_reservations_orders"
            )
    finally:
        engine.dispose()


def test_subscription_reminder_migration_preserves_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "migration-reminders.sqlite3"
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.attributes["database_url"] = url
    engine = build_engine(url)
    try:
        command.upgrade(config, "0008_risk_assessments")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO demo_users (id, display_name, dataset_version, created_at) "
                    "VALUES ('00000000000040008000000000000001', 'Prior Demo', 'old', '2026-10-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO accounts (id, demo_user_id, label, currency, "
                    "opening_balance_minor, created_at) VALUES "
                    "('10000000000040008000000000000001', "
                    "'00000000000040008000000000000001', 'Prior Account', 'CNY', "
                    "100000, '2026-10-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO subscriptions (id, account_id, merchant_key, merchant, "
                    "amount_minor, currency, billing_cycle, status, next_charge_at, "
                    "source_transaction_ids, version, created_at, updated_at) VALUES "
                    "('40000000000040008000000000000001', "
                    "'10000000000040008000000000000001', 'prior merchant', "
                    "'Prior Merchant', 3000, 'CNY', 'monthly', 'active', "
                    "'2026-11-01', '[]', 1, '2026-10-01', '2026-10-01')"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT merchant, amount_minor, reminder_days_before, "
                    "last_reminded_charge_at FROM subscriptions"
                )
            ).one()
            assert row == ("Prior Merchant", 3000, 3, None)
    finally:
        engine.dispose()


def test_phase1a_card_audit_data_survives_generic_audit_migration(tmp_path: Path) -> None:
    path = tmp_path / "migration-history.sqlite3"
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    engine = build_engine(url)
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.attributes["database_url"] = url
    try:
        command.upgrade(config, "0001_banking_core")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO demo_users (id, display_name, dataset_version, created_at) "
                    "VALUES (:id, 'Demo User One', 'phase1a-v1', '2026-10-18 00:00:00')"
                ),
                {"id": "00000000000040008000000000000001"},
            )
            connection.execute(
                text(
                    "INSERT INTO accounts "
                    "(id, demo_user_id, label, currency, opening_balance_minor, created_at) "
                    "VALUES (:id, :user_id, 'Everyday account', 'CNY', 1250000, "
                    "'2026-10-18 00:00:00')"
                ),
                {
                    "id": "10000000000040008000000000000001",
                    "user_id": "00000000000040008000000000000001",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO cards "
                    "(id, account_id, label, card_suffix, status, version, created_at, updated_at) "
                    "VALUES (:id, :account_id, 'Everyday debit', '1042', 'active', 1, "
                    "'2026-10-18 00:00:00', '2026-10-18 00:00:00')"
                ),
                {
                    "id": "20000000000040008000000000000001",
                    "account_id": "10000000000040008000000000000001",
                },
            )
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
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
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


def test_repeat_charge_migration_backfills_single_card_account_provenance(tmp_path: Path) -> None:
    path = tmp_path / "repeat-charge-history.sqlite3"
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    engine = build_engine(url)
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.attributes["database_url"] = url
    user_id = "00000000000040008000000000000001"
    account_id = "10000000000040008000000000000001"
    card_id = "20000000000040008000000000000001"
    transaction_id = "50000000000040008000000000000001"
    try:
        command.upgrade(config, "0004_transfers_and_investments")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO demo_users "
                    "(id, display_name, dataset_version, risk_level, created_at) "
                    "VALUES (:id, 'Demo User One', 'phase1d-v1', 3, '2026-10-18 00:00:00')"
                ),
                {"id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO accounts "
                    "(id, demo_user_id, label, currency, opening_balance_minor, balance_minor, "
                    "version, created_at, updated_at) "
                    "VALUES (:id, :user_id, 'Everyday account', 'CNY', 100000, 100000, 1, "
                    "'2026-10-18 00:00:00', '2026-10-18 00:00:00')"
                ),
                {"id": account_id, "user_id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO cards "
                    "(id, account_id, label, card_suffix, status, version, created_at, updated_at) "
                    "VALUES (:id, :account_id, 'Everyday debit', '1042', 'active', 1, "
                    "'2026-10-18 00:00:00', '2026-10-18 00:00:00')"
                ),
                {"id": card_id, "account_id": account_id},
            )
            connection.execute(
                text(
                    "INSERT INTO transactions "
                    "(id, account_id, synthetic_ref, direction, entry_kind, amount_minor, "
                    "currency, "
                    "merchant, category, description, occurred_at, created_at) "
                    "VALUES (:id, :account_id, 'legacy-bill', 'expense', 'bill', 3000, 'CNY', "
                    "'腾讯视频会员', '订阅', '模拟订阅流水', '2026-10-05 02:00:00', "
                    "'2026-10-18 00:00:00')"
                ),
                {"id": transaction_id, "account_id": account_id},
            )

        command.upgrade(config, "head")
        with sessionmaker(bind=engine)() as session:
            transaction = session.get(Transaction, UUID(transaction_id))
            assert transaction is not None
            assert transaction.card_id == UUID(card_id)
            foreign_keys = inspect(engine).get_foreign_keys("transactions")
            assert any(
                key["constrained_columns"] == ["card_id"] and key["referred_table"] == "cards"
                for key in foreign_keys
            )
    finally:
        engine.dispose()
