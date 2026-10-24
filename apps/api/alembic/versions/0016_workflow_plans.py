"""Persist validated dependency plans on AgentTask.

Revision ID: 0016_workflow_plans
Revises: 0015_birthday_plans
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_workflow_plans"
down_revision = "0015_birthday_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_tasks", sa.Column("workflow_plan", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_tasks", "workflow_plan")
