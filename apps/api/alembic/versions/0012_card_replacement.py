"""Track replacement of a lost synthetic card without reactivating it.

Revision ID: 0012_card_replacement
Revises: 0011_human_handoffs
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_card_replacement"
down_revision = "0011_human_handoffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("cards") as batch:
        batch.add_column(sa.Column("replaced_by_card_id", sa.Uuid(), nullable=True))
        batch.drop_constraint("status_allowed", type_="check")
        batch.create_check_constraint(
            "status_allowed", "status in ('active', 'frozen', 'lost', 'replaced')"
        )
        batch.create_foreign_key(
            "fk_cards_replaced_by_card_id_cards", "cards", ["replaced_by_card_id"], ["id"]
        )
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled', 'lost', 'replaced')",
        )
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("confirmation_challenges") as batch:
        batch.drop_constraint("challenge_target_status_allowed", type_="check")
        batch.create_check_constraint(
            "challenge_target_status_allowed",
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled', 'lost')",
        )
    with op.batch_alter_table("cards") as batch:
        batch.drop_constraint("fk_cards_replaced_by_card_id_cards", type_="foreignkey")
        batch.drop_column("replaced_by_card_id")
        batch.drop_constraint("status_allowed", type_="check")
        batch.create_check_constraint("status_allowed", "status in ('active', 'frozen', 'lost')")
    op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")
