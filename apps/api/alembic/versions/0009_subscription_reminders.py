"""Store local subscription reminder preferences and one delivered billing cycle.

Revision ID: 0009_subscription_reminders
Revises: 0008_risk_assessments
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_subscription_reminders"
down_revision = "0008_risk_assessments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("subscriptions") as batch:
        batch.add_column(
            sa.Column("reminder_days_before", sa.Integer(), nullable=False, server_default="3")
        )
        batch.add_column(sa.Column("last_reminded_charge_at", sa.DateTime(timezone=True)))
        batch.create_check_constraint(
            "subscription_reminder_days_allowed", "reminder_days_before between 0 and 30"
        )


def downgrade() -> None:
    with op.batch_alter_table("subscriptions") as batch:
        batch.drop_constraint("subscription_reminder_days_allowed", type_="check")
        batch.drop_column("last_reminded_charge_at")
        batch.drop_column("reminder_days_before")
