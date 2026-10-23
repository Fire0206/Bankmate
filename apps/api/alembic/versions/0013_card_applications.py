"""Add synthetic debit-card applications and confirmation binding.

Revision ID: 0013_card_applications
Revises: 0012_card_replacement
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_card_applications"
down_revision = "0012_card_replacement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_applications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("demo_users.id"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("issued_card_id", sa.Uuid(), sa.ForeignKey("cards.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('pending_confirmation', 'submitted', 'approved', 'rejected', 'cancelled')",
            name="card_application_status_allowed",
        ),
    )
    op.create_index("ix_card_applications_actor_id", "card_applications", ["actor_id"])
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.add_column(sa.Column("card_application_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("card_application_version", sa.Integer(), nullable=True))
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled', 'lost', 'replaced', 'submitted')",
        )
        batch.drop_constraint("challenge_single_resource", type_="check")
        batch.create_check_constraint(
            "challenge_single_resource",
            "(case when card_id is not null then 1 else 0 end + "
            "case when subscription_id is not null then 1 else 0 end + "
            "case when transfer_id is not null then 1 else 0 end + "
            "case when split_bill_id is not null then 1 else 0 end + "
            "case when investment_order_id is not null then 1 else 0 end + "
            "case when card_application_id is not null then 1 else 0 end) = 1",
        )
        batch.create_foreign_key(
            "fk_confirmation_card_application", "card_applications", ["card_application_id"], ["id"]
        )
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("fk_confirmation_card_application", type_="foreignkey")
        batch.drop_constraint("challenge_single_resource", type_="check")
        batch.create_check_constraint(
            "challenge_single_resource",
            "(case when card_id is not null then 1 else 0 end + "
            "case when subscription_id is not null then 1 else 0 end + "
            "case when transfer_id is not null then 1 else 0 end + "
            "case when split_bill_id is not null then 1 else 0 end + "
            "case when investment_order_id is not null then 1 else 0 end) = 1",
        )
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled', 'lost', 'replaced')",
        )
        batch.drop_column("card_application_version")
        batch.drop_column("card_application_id")
    op.drop_index("ix_card_applications_actor_id", table_name="card_applications")
    op.drop_table("card_applications")
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")
