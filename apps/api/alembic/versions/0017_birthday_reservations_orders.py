"""Add held birthday budgets, scheduled simulated orders and order confirmations.

Revision ID: 0017_birthday_reservations_orders
Revises: 0016_workflow_plans
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_birthday_reservations_orders"
down_revision = "0016_workflow_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("birthday_plans") as batch:
        batch.drop_constraint("birthday_status_allowed", type_="check")
        batch.create_check_constraint(
            "birthday_status_allowed",
            "status in ('pending_confirmation', 'scheduled', 'cancelled', 'completed')",
        )
        batch.add_column(sa.Column("card_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_birthday_plans_card_id_cards", "cards", ["card_id"], ["id"])

    op.create_table(
        "fund_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("birthday_plan_id", sa.Uuid(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("held_minor", sa.BigInteger(), nullable=False),
        sa.Column("consumed_minor", sa.BigInteger(), nullable=False),
        sa.Column("released_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="reservation_amount_positive"),
        sa.CheckConstraint("held_minor >= 0", name="reservation_held_nonnegative"),
        sa.CheckConstraint("consumed_minor >= 0", name="reservation_consumed_nonnegative"),
        sa.CheckConstraint("released_minor >= 0", name="reservation_released_nonnegative"),
        sa.CheckConstraint(
            "status in ('held', 'consumed', 'released')", name="reservation_status_allowed"
        ),
        sa.CheckConstraint(
            "amount_minor = held_minor + consumed_minor + released_minor",
            name="reservation_amount_reconciles",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["demo_users.id"], ondelete="RESTRICT", name="fk_fund_reservations_actor"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_fund_reservations_account",
        ),
        sa.ForeignKeyConstraint(
            ["birthday_plan_id"],
            ["birthday_plans.id"],
            ondelete="RESTRICT",
            name="fk_fund_reservations_plan",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("birthday_plan_id", name="uq_fund_reservations_birthday_plan"),
    )
    op.create_index(
        "ix_fund_reservations_account_status",
        "fund_reservations",
        ["account_id", "status"],
    )

    op.create_table(
        "birthday_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("merchant", sa.String(length=80), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("total_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("pickup_location", sa.String(length=120), nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("due_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("total_amount_minor > 0", name="birthday_order_amount_positive"),
        sa.CheckConstraint(
            "status in ('scheduled', 'awaiting_confirmation', 'confirmed', 'paid', "
            "'failed', 'cancelled')",
            name="birthday_order_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["demo_users.id"], ondelete="RESTRICT", name="fk_birthday_orders_actor"
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["birthday_plans.id"], ondelete="RESTRICT", name="fk_birthday_orders_plan"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], ondelete="RESTRICT", name="fk_birthday_orders_account"
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], ondelete="RESTRICT", name="fk_birthday_orders_card"
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            ondelete="RESTRICT",
            name="fk_birthday_orders_transaction",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", name="uq_birthday_orders_plan"),
    )
    op.create_index("ix_birthday_orders_due", "birthday_orders", ["status", "scheduled_for"])

    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.drop_constraint("challenge_single_resource", type_="check")
        batch.add_column(sa.Column("birthday_order_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("birthday_order_version", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_confirmation_challenges_birthday_order_id_birthday_orders",
            "birthday_orders",
            ["birthday_order_id"],
            ["id"],
        )
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled', 'lost', 'replaced', 'submitted', 'updated', 'paid')",
        )
        batch.create_check_constraint(
            "challenge_single_resource",
            "(case when card_id is not null then 1 else 0 end + "
            "case when subscription_id is not null then 1 else 0 end + "
            "case when transfer_id is not null then 1 else 0 end + "
            "case when split_bill_id is not null then 1 else 0 end + "
            "case when investment_order_id is not null then 1 else 0 end + "
            "case when card_application_id is not null then 1 else 0 end + "
            "case when birthday_plan_id is not null then 1 else 0 end + "
            "case when birthday_order_id is not null then 1 else 0 end) = 1",
        )


def downgrade() -> None:
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_single_resource", type_="check")
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.drop_constraint(
            "fk_confirmation_challenges_birthday_order_id_birthday_orders", type_="foreignkey"
        )
        batch.drop_column("birthday_order_version")
        batch.drop_column("birthday_order_id")
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled', 'lost', 'replaced', 'submitted', 'updated')",
        )
        batch.create_check_constraint(
            "challenge_single_resource",
            "(case when card_id is not null then 1 else 0 end + "
            "case when subscription_id is not null then 1 else 0 end + "
            "case when transfer_id is not null then 1 else 0 end + "
            "case when split_bill_id is not null then 1 else 0 end + "
            "case when investment_order_id is not null then 1 else 0 end + "
            "case when card_application_id is not null then 1 else 0 end + "
            "case when birthday_plan_id is not null then 1 else 0 end) = 1",
        )
    op.drop_index("ix_birthday_orders_due", table_name="birthday_orders")
    op.drop_table("birthday_orders")
    op.drop_index("ix_fund_reservations_account_status", table_name="fund_reservations")
    op.drop_table("fund_reservations")
    with op.batch_alter_table("birthday_plans") as batch:
        batch.drop_constraint("fk_birthday_plans_card_id_cards", type_="foreignkey")
        batch.drop_column("card_id")
        batch.drop_constraint("birthday_status_allowed", type_="check")
        batch.create_check_constraint(
            "birthday_status_allowed",
            "status in ('pending_confirmation', 'scheduled', 'cancelled')",
        )
