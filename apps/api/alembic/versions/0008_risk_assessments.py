"""Persist deterministic synthetic investment risk assessments.

Revision ID: 0008_risk_assessments
Revises: 0007_transfer_phone_remark
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_risk_assessments"
down_revision = "0007_transfer_phone_remark"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("questionnaire_version", sa.String(32), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("answers_hash", sa.String(64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["demo_users.id"],
            name="fk_risk_assessments_actor_id_demo_users",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_risk_assessments_actor_key"),
        sa.CheckConstraint("risk_level between 1 and 5", name="risk_assessment_level_allowed"),
    )
    op.create_index(
        "ix_risk_assessments_actor_created", "risk_assessments", ["actor_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_risk_assessments_actor_created", table_name="risk_assessments")
    op.drop_table("risk_assessments")
