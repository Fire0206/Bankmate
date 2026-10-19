"""Add simulated transfers, bill splits, and investment accounts.

Revision ID: 0004_transfers_and_investments
Revises: 0003_bills_and_subscriptions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_transfers_and_investments"
down_revision: str | None = "0003_bills_and_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "demo_users",
        sa.Column("risk_level", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "accounts",
        sa.Column("balance_minor", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "accounts",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("'1970-01-01 00:00:00'"),
        ),
    )
    op.execute(sa.text("UPDATE accounts SET balance_minor = opening_balance_minor"))
    op.execute(sa.text("UPDATE accounts SET updated_at = created_at"))

    op.execute(
        sa.text(
            "CREATE TRIGGER demo_users_risk_level_insert "
            "BEFORE INSERT ON demo_users WHEN NEW.risk_level NOT BETWEEN 1 AND 5 "
            "BEGIN SELECT RAISE(ABORT, 'demo_user_risk_level_allowed'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER demo_users_risk_level_update "
            "BEFORE UPDATE OF risk_level ON demo_users WHEN NEW.risk_level NOT BETWEEN 1 AND 5 "
            "BEGIN SELECT RAISE(ABORT, 'demo_user_risk_level_allowed'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER accounts_balance_version_insert "
            "BEFORE INSERT ON accounts WHEN NEW.balance_minor < 0 OR NEW.version < 1 "
            "BEGIN SELECT RAISE(ABORT, 'account_balance_or_version_invalid'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER accounts_balance_version_update "
            "BEFORE UPDATE OF balance_minor, version ON accounts "
            "WHEN NEW.balance_minor < 0 OR NEW.version < 1 "
            "BEGIN SELECT RAISE(ABORT, 'account_balance_or_version_invalid'); END"
        )
    )

    op.add_column(
        "transactions",
        sa.Column("entry_kind", sa.String(length=16), nullable=False, server_default="bill"),
    )
    with op.batch_alter_table("transactions") as batch:
        batch.alter_column("entry_kind", existing_type=sa.String(length=16), server_default=None)
        batch.create_check_constraint(
            "transaction_entry_kind_allowed",
            "entry_kind in ('bill', 'transfer', 'investment')",
        )

    op.create_table(
        "payees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("destination_account_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("normalized_name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["demo_users.id"],
            ondelete="RESTRICT",
            name="fk_payees_actor_id_demo_users",
        ),
        sa.ForeignKeyConstraint(
            ["destination_account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_payees_destination_account_id_accounts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payees"),
        sa.UniqueConstraint("actor_id", "normalized_name", name="uq_payees_actor_name"),
    )
    op.create_index("ix_payees_actor_name", "payees", ["actor_id", "normalized_name"])

    op.create_table(
        "transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("source_account_id", sa.Uuid(), nullable=False),
        sa.Column("destination_account_id", sa.Uuid(), nullable=False),
        sa.Column("payee_id", sa.Uuid(), nullable=False),
        sa.Column("payee_name", sa.String(length=80), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("transfer_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="transfer_amount_positive"),
        sa.CheckConstraint("length(currency) = 3", name="transfer_currency_code_length"),
        sa.CheckConstraint(
            "transfer_type in ('immediate', 'scheduled')", name="transfer_type_allowed"
        ),
        sa.CheckConstraint(
            "status in ('awaiting_confirmation', 'scheduled', 'executed', 'cancelled', 'failed')",
            name="transfer_status_allowed",
        ),
        sa.CheckConstraint("version >= 1", name="transfer_version_positive"),
        sa.CheckConstraint(
            "(transfer_type = 'scheduled' and scheduled_at is not null) or "
            "(transfer_type = 'immediate' and scheduled_at is null)",
            name="transfer_schedule_matches_type",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["demo_users.id"],
            ondelete="RESTRICT",
            name="fk_transfers_actor_id_demo_users",
        ),
        sa.ForeignKeyConstraint(
            ["source_account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_transfers_source_account_id_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["destination_account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_transfers_destination_account_id_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["payee_id"], ["payees.id"], ondelete="RESTRICT", name="fk_transfers_payee_id_payees"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transfers"),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_transfers_actor_idempotency"),
    )
    op.create_index("ix_transfers_actor_created_at", "transfers", ["actor_id", "created_at"])
    op.create_index("ix_transfers_status_scheduled_at", "transfers", ["status", "scheduled_at"])

    op.create_table(
        "split_bills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("total_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("participant_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("total_amount_minor > 0", name="split_bill_amount_positive"),
        sa.CheckConstraint("length(currency) = 3", name="split_bill_currency_code_length"),
        sa.CheckConstraint("participant_count between 2 and 11", name="split_bill_count_allowed"),
        sa.CheckConstraint(
            "status in ('awaiting_confirmation', 'open', 'settled', 'cancelled', 'failed')",
            name="split_bill_status_allowed",
        ),
        sa.CheckConstraint("version >= 1", name="split_bill_version_positive"),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["demo_users.id"],
            ondelete="RESTRICT",
            name="fk_split_bills_actor_id_demo_users",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_split_bills_account_id_accounts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_split_bills"),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_split_bills_actor_idempotency"),
    )
    op.create_index("ix_split_bills_actor_created_at", "split_bills", ["actor_id", "created_at"])

    op.create_table(
        "split_participants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("split_bill_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_minor > 0", name="split_participant_amount_positive"),
        sa.CheckConstraint(
            "status in ('organizer_paid', 'pending', 'paid')",
            name="split_participant_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["split_bill_id"],
            ["split_bills.id"],
            ondelete="CASCADE",
            name="fk_split_participants_split_bill_id_split_bills",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_split_participants"),
        sa.UniqueConstraint("split_bill_id", "sequence", name="uq_split_participants_sequence"),
    )
    op.create_index("ix_split_participants_split_bill_id", "split_participants", ["split_bill_id"])

    op.create_table(
        "investment_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("risk_level", sa.Integer(), nullable=False),
        sa.Column("minimum_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("annual_yield_bps", sa.Integer(), nullable=False),
        sa.Column("term_days", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("risk_level between 1 and 5", name="investment_product_risk_allowed"),
        sa.CheckConstraint("minimum_amount_minor > 0", name="investment_product_minimum_positive"),
        sa.CheckConstraint("unit_price_minor > 0", name="investment_product_price_positive"),
        sa.CheckConstraint(
            "annual_yield_bps between -10000 and 100000", name="investment_product_yield_allowed"
        ),
        sa.CheckConstraint("term_days >= 0", name="investment_product_term_nonnegative"),
        sa.CheckConstraint("length(currency) = 3", name="investment_product_currency_code_length"),
        sa.PrimaryKeyConstraint("id", name="pk_investment_products"),
        sa.UniqueConstraint("code", name="uq_investment_products_code"),
    )

    op.create_table(
        "investment_holdings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("units_micros", sa.BigInteger(), nullable=False),
        sa.Column("purchase_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("units_micros >= 0", name="investment_holding_units_nonnegative"),
        sa.CheckConstraint("purchase_price_minor > 0", name="investment_holding_price_positive"),
        sa.CheckConstraint("version >= 1", name="investment_holding_version_positive"),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["demo_users.id"],
            ondelete="RESTRICT",
            name="fk_investment_holdings_actor_id_demo_users",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_investment_holdings_account_id_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["investment_products.id"],
            ondelete="RESTRICT",
            name="fk_investment_holdings_product_id_investment_products",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_investment_holdings"),
    )
    op.create_index(
        "ix_investment_holdings_actor_account", "investment_holdings", ["actor_id", "account_id"]
    )

    op.create_table(
        "investment_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("holding_id", sa.Uuid(), nullable=True),
        sa.Column("order_type", sa.String(length=8), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("units_micros", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("order_type in ('buy', 'redeem')", name="investment_order_type_allowed"),
        sa.CheckConstraint("amount_minor > 0", name="investment_order_amount_positive"),
        sa.CheckConstraint("units_micros >= 0", name="investment_order_units_nonnegative"),
        sa.CheckConstraint(
            "status in ('awaiting_confirmation', 'executed', 'cancelled', 'failed')",
            name="investment_order_status_allowed",
        ),
        sa.CheckConstraint("version >= 1", name="investment_order_version_positive"),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["demo_users.id"],
            ondelete="RESTRICT",
            name="fk_investment_orders_actor_id_demo_users",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_investment_orders_account_id_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["investment_products.id"],
            ondelete="RESTRICT",
            name="fk_investment_orders_product_id_investment_products",
        ),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["investment_holdings.id"],
            ondelete="RESTRICT",
            name="fk_investment_orders_holding_id_investment_holdings",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_investment_orders"),
        sa.UniqueConstraint(
            "actor_id", "idempotency_key", name="uq_investment_orders_actor_idempotency"
        ),
    )
    op.create_index(
        "ix_investment_orders_actor_created_at", "investment_orders", ["actor_id", "created_at"]
    )

    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_single_resource", type_="check")
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.add_column(sa.Column("transfer_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("split_bill_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("investment_order_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("transfer_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("split_bill_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("investment_order_version", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_confirmation_challenges_transfer_id_transfers", "transfers", ["transfer_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_confirmation_challenges_split_bill_id_split_bills",
            "split_bills",
            ["split_bill_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_confirmation_challenges_investment_order_id_investment_orders",
            "investment_orders",
            ["investment_order_id"],
            ["id"],
        )
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled')",
        )
        batch.create_check_constraint(
            "challenge_single_resource",
            "(case when card_id is not null then 1 else 0 end + "
            "case when subscription_id is not null then 1 else 0 end + "
            "case when transfer_id is not null then 1 else 0 end + "
            "case when split_bill_id is not null then 1 else 0 end + "
            "case when investment_order_id is not null then 1 else 0 end) = 1",
        )


def downgrade() -> None:
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_single_resource", type_="check")
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.drop_constraint(
            "fk_confirmation_challenges_investment_order_id_investment_orders", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_confirmation_challenges_split_bill_id_split_bills", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_confirmation_challenges_transfer_id_transfers", type_="foreignkey"
        )
        batch.drop_column("investment_order_version")
        batch.drop_column("split_bill_version")
        batch.drop_column("transfer_version")
        batch.drop_column("investment_order_id")
        batch.drop_column("split_bill_id")
        batch.drop_column("transfer_id")
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled')",
        )
        batch.create_check_constraint(
            "challenge_single_resource",
            "(card_id is not null and subscription_id is null) or "
            "(card_id is null and subscription_id is not null)",
        )
    op.drop_index("ix_investment_orders_actor_created_at", table_name="investment_orders")
    op.drop_table("investment_orders")
    op.drop_index("ix_investment_holdings_actor_account", table_name="investment_holdings")
    op.drop_table("investment_holdings")
    op.drop_table("investment_products")
    op.drop_index("ix_split_participants_split_bill_id", table_name="split_participants")
    op.drop_table("split_participants")
    op.drop_index("ix_split_bills_actor_created_at", table_name="split_bills")
    op.drop_table("split_bills")
    op.drop_index("ix_transfers_status_scheduled_at", table_name="transfers")
    op.drop_index("ix_transfers_actor_created_at", table_name="transfers")
    op.drop_table("transfers")
    op.drop_index("ix_payees_actor_name", table_name="payees")
    op.drop_table("payees")
    op.execute("DROP TRIGGER IF EXISTS accounts_balance_version_update")
    op.execute("DROP TRIGGER IF EXISTS accounts_balance_version_insert")
    op.execute("DROP TRIGGER IF EXISTS demo_users_risk_level_update")
    op.execute("DROP TRIGGER IF EXISTS demo_users_risk_level_insert")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("transaction_entry_kind_allowed", type_="check")
        batch.drop_column("entry_kind")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("version")
        batch.drop_column("balance_minor")
    with op.batch_alter_table("demo_users") as batch:
        batch.drop_column("risk_level")
