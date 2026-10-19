"""Add synthetic card provenance for repeated-charge evidence.

Revision ID: 0005_repeat_charge_evidence
Revises: 0004_transfers_and_investments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_repeat_charge_evidence"
down_revision: str | None = "0004_transfers_and_investments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("card_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_transactions_card_id_cards", "cards", ["card_id"], ["id"], ondelete="RESTRICT"
        )
    op.create_index("ix_transactions_card_id", "transactions", ["card_id"])
    op.execute(
        sa.text(
            "UPDATE transactions SET card_id = ("
            "SELECT min(cards.id) FROM cards WHERE cards.account_id = transactions.account_id) "
            "WHERE entry_kind = 'bill' AND ("
            "SELECT count(*) FROM cards WHERE cards.account_id = transactions.account_id) = 1"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_card_id", table_name="transactions")
    op.drop_column("transactions", "card_id")
