"""Local simulated human handoff tickets.

Revision ID: 0011_human_handoffs
Revises: 0010_card_lost
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_human_handoffs"
down_revision = "0010_card_lost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "human_handoffs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("demo_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("agent_tasks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("outcome", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('pending', 'in_progress', 'resolved')", name="human_handoff_status_allowed"
        ),
        sa.UniqueConstraint("task_id", name="uq_human_handoff_task"),
    )
    op.create_index("ix_human_handoffs_actor_id", "human_handoffs", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_human_handoffs_actor_id", table_name="human_handoffs")
    op.drop_table("human_handoffs")
