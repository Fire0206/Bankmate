"""Add synthetic debit-card purchase controls.

Revision ID: 0014_card_controls
Revises: 0013_card_applications
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_card_controls"
down_revision = "0013_card_applications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("cards") as batch:
        batch.add_column(
            sa.Column("single_limit_minor", sa.BigInteger(), nullable=False, server_default="50000")
        )
        batch.add_column(
            sa.Column("daily_limit_minor", sa.BigInteger(), nullable=False, server_default="100000")
        )
        batch.add_column(
            sa.Column("online_enabled", sa.Boolean(), nullable=False, server_default="1")
        )
        batch.create_check_constraint("card_single_limit_positive", "single_limit_minor > 0")
        batch.create_check_constraint("card_daily_limit_positive", "daily_limit_minor > 0")
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled', 'lost', 'replaced', 'submitted', 'updated')",
        )
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled', 'lost', 'replaced', 'submitted')",
        )
    with op.batch_alter_table("cards") as batch:
        batch.drop_constraint("card_single_limit_positive", type_="check")
        batch.drop_constraint("card_daily_limit_positive", type_="check")
        batch.drop_column("online_enabled")
        batch.drop_column("daily_limit_minor")
        batch.drop_column("single_limit_minor")
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")
