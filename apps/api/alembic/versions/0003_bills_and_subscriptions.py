"""Add synthetic transaction and subscription foundations.

Revision ID: 0003_bills_and_subscriptions
Revises: 0002_agent_workflow_and_audit
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_bills_and_subscriptions"
down_revision: str | None = "0002_agent_workflow_and_audit"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("synthetic_ref", sa.String(length=80), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("merchant", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("description", sa.String(length=240), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="transaction_amount_positive"),
        sa.CheckConstraint("length(currency) = 3", name="transaction_currency_code_length"),
        sa.CheckConstraint(
            "direction in ('income', 'expense')", name="transaction_direction_allowed"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_transactions_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.UniqueConstraint("synthetic_ref", name="uq_transactions_synthetic_ref"),
    )
    op.create_index(
        "ix_transactions_account_occurred_at", "transactions", ["account_id", "occurred_at"]
    )
    op.create_index(
        "ix_transactions_account_category_occurred_at",
        "transactions",
        ["account_id", "category", "occurred_at"],
    )
    op.create_index(
        "ix_transactions_account_merchant_occurred_at",
        "transactions",
        ["account_id", "merchant", "occurred_at"],
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_key", sa.String(length=120), nullable=False),
        sa.Column("merchant", sa.String(length=120), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("billing_cycle", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("next_charge_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_transaction_ids", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="subscription_amount_positive"),
        sa.CheckConstraint("length(currency) = 3", name="subscription_currency_code_length"),
        sa.CheckConstraint("billing_cycle = 'monthly'", name="subscription_billing_cycle_allowed"),
        sa.CheckConstraint(
            "status in ('active', 'paused', 'cancelled')", name="subscription_status_allowed"
        ),
        sa.CheckConstraint("version >= 1", name="subscription_version_positive"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_subscriptions_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subscriptions"),
        sa.UniqueConstraint("account_id", "merchant_key", name="uq_subscriptions_account_merchant"),
    )
    op.create_index("ix_subscriptions_account_status", "subscriptions", ["account_id", "status"])

    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.alter_column("card_id", existing_type=sa.Uuid(), nullable=True)
        batch.alter_column("card_version", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("subscription_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("subscription_version", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_confirmation_challenges_subscription_id_subscriptions",
            "subscriptions",
            ["subscription_id"],
            ["id"],
        )
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled')",
        )
        batch.create_check_constraint(
            "challenge_single_resource",
            "(card_id is not null and subscription_id is null) or "
            "(card_id is null and subscription_id is not null)",
        )


def downgrade() -> None:
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_single_resource", type_="check")
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.drop_constraint(
            "fk_confirmation_challenges_subscription_id_subscriptions", type_="foreignkey"
        )
        batch.drop_column("subscription_version")
        batch.drop_column("subscription_id")
        batch.alter_column("card_version", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("card_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_check_constraint(
            "challenge_target_status_allowed", "target_status in ('active', 'frozen')"
        )
    op.drop_index("ix_subscriptions_account_status", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("ix_transactions_account_merchant_occurred_at", table_name="transactions")
    op.drop_index("ix_transactions_account_category_occurred_at", table_name="transactions")
    op.drop_index("ix_transactions_account_occurred_at", table_name="transactions")
    op.drop_table("transactions")
