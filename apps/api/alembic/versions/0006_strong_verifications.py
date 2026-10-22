"""Persist actor-bound demo verification lifecycle.

Revision ID: 0006_strong_verifications
Revises: 0005_repeat_charge_evidence
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_strong_verifications"
down_revision = "0005_repeat_charge_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strong_verifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "confirmation_id",
            sa.Uuid(),
            sa.ForeignKey("confirmation_challenges.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("demo_users.id"), nullable=False),
        sa.Column("binding_hash", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("salt", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0 and attempts <= 5", name="verification_attempts_range"),
        sa.CheckConstraint(
            "status in ('pending', 'verified', 'consumed', 'locked', 'expired', 'invalidated')",
            name="verification_status_allowed",
        ),
        sa.UniqueConstraint("confirmation_id", name="uq_verification_confirmation"),
    )


def downgrade() -> None:
    op.drop_table("strong_verifications")
