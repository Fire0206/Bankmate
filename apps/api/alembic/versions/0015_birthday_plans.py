"""Add confirmed birthday budget intentions and due reminders.

Revision ID: 0015_birthday_plans
Revises: 0014_card_controls
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_birthday_plans"
down_revision = "0014_card_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "birthday_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("demo_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("birthday_on", sa.Date(), nullable=False),
        sa.Column("purchase_on", sa.Date(), nullable=False),
        sa.Column("budget_minor", sa.BigInteger(), nullable=False),
        sa.Column("catalog_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("budget_minor > 0", name="birthday_budget_positive"),
        sa.CheckConstraint("catalog_total_minor > 0", name="birthday_catalog_total_positive"),
        sa.CheckConstraint(
            "status in ('pending_confirmation', 'scheduled', 'cancelled')",
            name="birthday_status_allowed",
        ),
    )
    op.create_index("ix_birthday_plans_actor_due", "birthday_plans", ["actor_id", "purchase_on"])
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_single_resource", type_="check")
        batch.add_column(sa.Column("birthday_plan_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("birthday_plan_version", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_confirmation_birthday_plan", "birthday_plans", ["birthday_plan_id"], ["id"]
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
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_single_resource", type_="check")
        batch.drop_constraint("fk_confirmation_birthday_plan", type_="foreignkey")
        batch.drop_column("birthday_plan_version")
        batch.drop_column("birthday_plan_id")
        batch.create_check_constraint(
            "challenge_single_resource",
            "(case when card_id is not null then 1 else 0 end + "
            "case when subscription_id is not null then 1 else 0 end + "
            "case when transfer_id is not null then 1 else 0 end + "
            "case when split_bill_id is not null then 1 else 0 end + "
            "case when investment_order_id is not null then 1 else 0 end + "
            "case when card_application_id is not null then 1 else 0 end) = 1",
        )
    op.drop_index("ix_birthday_plans_actor_due", table_name="birthday_plans")
    op.drop_table("birthday_plans")
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")
