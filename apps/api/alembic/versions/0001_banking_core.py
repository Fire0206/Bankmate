"""Create the initial synthetic Banking Core tables.

Revision ID: 0001_banking_core
Revises:
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_banking_core"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("dataset_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(display_name) > 0", name="display_name_not_empty"),
        sa.PrimaryKeyConstraint("id", name="pk_demo_users"),
        sa.UniqueConstraint("display_name", name="uq_demo_users_display_name"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("demo_user_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("opening_balance_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(currency) = 3", name="currency_code_length"),
        sa.CheckConstraint("opening_balance_minor >= 0", name="opening_balance_nonnegative"),
        sa.ForeignKeyConstraint(
            ["demo_user_id"],
            ["demo_users.id"],
            name="fk_accounts_demo_user_id_demo_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
    )
    op.create_index("ix_accounts_demo_user_id", "accounts", ["demo_user_id"], unique=False)
    op.create_table(
        "cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("card_suffix", sa.String(length=4), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(card_suffix) = 4", name="card_suffix_length"),
        sa.CheckConstraint("status in ('active', 'frozen')", name="status_allowed"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_cards_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cards"),
    )
    op.create_index("ix_cards_account_id", "cards", ["account_id"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("previous_status", sa.String(length=16), nullable=False),
        sa.Column("new_status", sa.String(length=16), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("previous_status <> new_status", name="status_must_change"),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["demo_users.id"],
            name="fk_audit_events_actor_id_demo_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["cards.id"],
            name="fk_audit_events_card_id_cards",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"], unique=False)
    op.create_index(
        "ix_audit_events_card_occurred_at",
        "audit_events",
        ["card_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_card_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_cards_account_id", table_name="cards")
    op.drop_table("cards")
    op.drop_index("ix_accounts_demo_user_id", table_name="accounts")
    op.drop_table("accounts")
    op.drop_table("demo_users")
