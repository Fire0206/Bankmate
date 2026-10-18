"""Add the card-agent workflow and general-purpose audit metadata.

Revision ID: 0002_agent_workflow_and_audit
Revises: 0001_banking_core
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_agent_workflow_and_audit"
down_revision: str | None = "0001_banking_core"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("request_text", sa.String(length=1000), nullable=False),
        sa.Column("provider_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=1200), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(request_text) between 1 and 1000", name="task_request_length"),
        sa.CheckConstraint("version >= 1", name="task_version_positive"),
        sa.CheckConstraint(
            "status in ('pending', 'planning', 'awaiting_input', 'awaiting_confirmation', "
            "'running', 'completed', 'failed', 'cancelled')",
            name="agent_task_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["demo_users.id"], name="fk_agent_tasks_actor_id_demo_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_tasks"),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_agent_tasks_actor_idempotency"),
    )
    op.create_index("ix_agent_tasks_actor_created_at", "agent_tasks", ["actor_id", "created_at"])
    op.create_index("ix_agent_tasks_conversation_id", "agent_tasks", ["conversation_id"])

    op.create_table(
        "task_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('pending', 'running', 'awaiting_confirmation', 'succeeded', "
            "'failed', 'cancelled')",
            name="task_step_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["agent_tasks.id"],
            name="fk_task_steps_task_id_agent_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_task_steps"),
        sa.UniqueConstraint("task_id", "sequence", name="uq_task_steps_task_sequence"),
        sa.UniqueConstraint("task_id", "idempotency_key", name="uq_task_steps_task_idempotency"),
    )
    op.create_index("ix_task_steps_task_id", "task_steps", ["task_id"])

    op.create_table(
        "tool_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("tool_version", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result_summary", sa.String(length=500), nullable=True),
        sa.Column("result_data", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('accepted', 'awaiting_confirmation', 'running', 'succeeded', "
            "'failed', 'cancelled')",
            name="tool_execution_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["demo_users.id"], name="fk_tool_executions_actor_id_demo_users"
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["task_steps.id"],
            name="fk_tool_executions_step_id_task_steps",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["agent_tasks.id"],
            name="fk_tool_executions_task_id_agent_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tool_executions"),
        sa.UniqueConstraint(
            "actor_id", "tool_name", "idempotency_key", name="uq_tool_executions_actor_tool_key"
        ),
    )
    op.create_index("ix_tool_executions_task_id", "tool_executions", ["task_id"])

    op.create_table(
        "confirmation_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("tool_execution_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("tool_version", sa.String(length=16), nullable=False),
        sa.Column("target_status", sa.String(length=16), nullable=False),
        sa.Column("parameters_hash", sa.String(length=64), nullable=False),
        sa.Column("card_version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_status in ('active', 'frozen')", name="challenge_target_status_allowed"
        ),
        sa.CheckConstraint(
            "status in ('pending', 'consumed', 'expired', 'cancelled', 'invalidated')",
            name="confirmation_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["demo_users.id"], name="fk_confirmation_challenges_actor_id_demo_users"
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name="fk_confirmation_challenges_card_id_cards"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["agent_tasks.id"],
            name="fk_confirmation_challenges_task_id_agent_tasks",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_execution_id"],
            ["tool_executions.id"],
            name="fk_confirmation_challenges_tool_execution_id_tool_executions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_confirmation_challenges"),
        sa.UniqueConstraint(
            "actor_id", "idempotency_key", name="uq_confirmation_actor_idempotency"
        ),
        sa.UniqueConstraint(
            "tool_execution_id", name="uq_confirmation_challenges_tool_execution_id"
        ),
    )
    op.create_index("ix_confirmation_challenges_task_id", "confirmation_challenges", ["task_id"])

    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(sa.Column("resource_type", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("resource_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("task_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("tool_execution_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("outcome", sa.String(length=16), nullable=False, server_default="succeeded")
        )
        batch.add_column(sa.Column("before_state", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("after_state", sa.JSON(), nullable=True))

    op.execute(
        "UPDATE audit_events SET resource_type = 'card', resource_id = card_id, "
        "outcome = 'succeeded'"
    )

    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("status_must_change", type_="check")
        batch.create_check_constraint(
            "status_must_change",
            "card_id is null or previous_status is null or new_status is null "
            "or previous_status <> new_status",
        )
        batch.alter_column("card_id", existing_type=sa.Uuid(), nullable=True)
        batch.alter_column("previous_status", existing_type=sa.String(length=16), nullable=True)
        batch.alter_column("new_status", existing_type=sa.String(length=16), nullable=True)
        batch.alter_column("resource_version", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("resource_type", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("resource_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column(
            "outcome",
            existing_type=sa.String(length=16),
            nullable=False,
            server_default=None,
        )
        batch.create_foreign_key(
            "fk_audit_events_task_id_agent_tasks", "agent_tasks", ["task_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_audit_events_tool_execution_id_tool_executions",
            "tool_executions",
            ["tool_execution_id"],
            ["id"],
        )

    op.create_index("ix_audit_events_task_id", "audit_events", ["task_id"])
    op.create_index(
        "ix_audit_events_resource", "audit_events", ["resource_type", "resource_id", "occurred_at"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    generic_events = bind.execute(
        sa.text("SELECT count(*) FROM audit_events WHERE card_id IS NULL")
    ).scalar_one()
    if generic_events:
        raise RuntimeError(
            "Cannot downgrade while generic audit events exist; export/preserve them first."
        )

    op.drop_index("ix_audit_events_resource", table_name="audit_events")
    op.drop_index("ix_audit_events_task_id", table_name="audit_events")
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint(
            "fk_audit_events_tool_execution_id_tool_executions", type_="foreignkey"
        )
        batch.drop_constraint("fk_audit_events_task_id_agent_tasks", type_="foreignkey")
        batch.drop_column("after_state")
        batch.drop_column("before_state")
        batch.drop_column("outcome")
        batch.drop_column("tool_execution_id")
        batch.drop_column("task_id")
        batch.drop_column("resource_id")
        batch.drop_column("resource_type")
        batch.alter_column("card_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("previous_status", existing_type=sa.String(length=16), nullable=False)
        batch.alter_column("new_status", existing_type=sa.String(length=16), nullable=False)
        batch.alter_column("resource_version", existing_type=sa.Integer(), nullable=False)

    op.drop_index("ix_confirmation_challenges_task_id", table_name="confirmation_challenges")
    op.drop_table("confirmation_challenges")
    op.drop_index("ix_tool_executions_task_id", table_name="tool_executions")
    op.drop_table("tool_executions")
    op.drop_index("ix_task_steps_task_id", table_name="task_steps")
    op.drop_table("task_steps")
    op.drop_index("ix_agent_tasks_conversation_id", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_actor_created_at", table_name="agent_tasks")
    op.drop_table("agent_tasks")
