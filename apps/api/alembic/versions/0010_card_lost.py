"""Allow distinct lost-card confirmation status.

Revision ID: 0010_card_lost
Revises: 0009_subscription_reminders
"""

from alembic import op

revision = "0010_card_lost"
down_revision = "0009_subscription_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("cards") as batch:
        batch.drop_constraint("status_allowed", type_="check")
        batch.create_check_constraint("status_allowed", "status in ('active', 'frozen', 'lost')")
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled', 'lost')",
        )
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("cards") as batch:
        batch.drop_constraint("status_allowed", type_="check")
        batch.create_check_constraint("status_allowed", "status in ('active', 'frozen')")
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled')",
        )
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")
