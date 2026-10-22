"""Add synthetic saved-recipient phone and transfer remark.

Revision ID: 0007_transfer_phone_remark
Revises: 0006_strong_verifications
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_transfer_phone_remark"
down_revision = "0006_strong_verifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payees", sa.Column("phone_number", sa.String(11), nullable=True))
    op.create_index("uq_payees_actor_phone", "payees", ["actor_id", "phone_number"], unique=True)
    op.add_column("transfers", sa.Column("remark", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("transfers", "remark")
    op.drop_index("uq_payees_actor_phone", table_name="payees")
    op.drop_column("payees", "phone_number")
