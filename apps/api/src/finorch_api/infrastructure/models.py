from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finorch_api.domain.cards import CardStatus
from finorch_api.infrastructure.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class DemoUser(Base):
    __tablename__ = "demo_users"
    __table_args__ = (CheckConstraint("length(display_name) > 0", name="display_name_not_empty"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    dataset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    accounts: Mapped[list["Account"]] = relationship(back_populates="demo_user")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="currency_code_length"),
        CheckConstraint("opening_balance_minor >= 0", name="opening_balance_nonnegative"),
        Index("ix_accounts_demo_user_id", "demo_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    demo_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "demo_users.id", name="fk_accounts_demo_user_id_demo_users", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    opening_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    demo_user: Mapped[DemoUser] = relationship(back_populates="accounts")
    cards: Mapped[list["Card"]] = relationship(back_populates="account")


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("length(card_suffix) = 4", name="card_suffix_length"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_cards_account_id", "account_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", name="fk_cards_account_id_accounts", ondelete="RESTRICT"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    card_suffix: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[CardStatus] = mapped_column(
        SqlEnum(
            CardStatus,
            name="card_status",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    __mapper_args__ = {"version_id_col": version}

    account: Mapped[Account] = relationship(back_populates="cards")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "card_id is null or previous_status is null or new_status is null "
            "or previous_status <> new_status",
            name="status_must_change",
        ),
        Index("ix_audit_events_actor_id", "actor_id"),
        Index("ix_audit_events_card_occurred_at", "card_id", "occurred_at"),
        Index("ix_audit_events_task_id", "task_id"),
        Index("ix_audit_events_resource", "resource_type", "resource_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "demo_users.id", name="fk_audit_events_actor_id_demo_users", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    card_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cards.id", name="fk_audit_events_card_id_cards", ondelete="RESTRICT"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resource_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_tasks.id", name="fk_audit_events_task_id_agent_tasks"),
        nullable=True,
    )
    tool_execution_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tool_executions.id", name="fk_audit_events_tool_execution_id_tool_executions"),
        nullable=True,
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="succeeded")
    before_state: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (
        UniqueConstraint("actor_id", "idempotency_key", name="uq_agent_tasks_actor_idempotency"),
        CheckConstraint("length(request_text) between 1 and 1000", name="task_request_length"),
        CheckConstraint("version >= 1", name="task_version_positive"),
        CheckConstraint(
            "status in ('pending', 'planning', 'awaiting_input', 'awaiting_confirmation', "
            "'running', 'completed', 'failed', 'cancelled')",
            name="agent_task_status_allowed",
        ),
        Index("ix_agent_tasks_actor_created_at", "actor_id", "created_at"),
        Index("ix_agent_tasks_conversation_id", "conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("demo_users.id", name="fk_agent_tasks_actor_id_demo_users"),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_text: Mapped[str] = mapped_column(String(1000), nullable=False)
    provider_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(1200), nullable=False, default="")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    __mapper_args__ = {"version_id_col": version}


class TaskStep(Base):
    __tablename__ = "task_steps"
    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_task_steps_task_sequence"),
        UniqueConstraint("task_id", "idempotency_key", name="uq_task_steps_task_idempotency"),
        CheckConstraint(
            "status in ('pending', 'running', 'awaiting_confirmation', 'succeeded', "
            "'failed', 'cancelled')",
            name="task_step_status_allowed",
        ),
        Index("ix_task_steps_task_id", "task_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_tasks.id", name="fk_task_steps_task_id_agent_tasks", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "tool_name", "idempotency_key", name="uq_tool_executions_actor_tool_key"
        ),
        Index("ix_tool_executions_task_id", "task_id"),
        CheckConstraint(
            "status in ('accepted', 'awaiting_confirmation', 'running', 'succeeded', "
            "'failed', 'cancelled')",
            name="tool_execution_status_allowed",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "agent_tasks.id", name="fk_tool_executions_task_id_agent_tasks", ondelete="CASCADE"
        ),
        nullable=False,
    )
    step_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "task_steps.id", name="fk_tool_executions_step_id_task_steps", ondelete="CASCADE"
        ),
        nullable=False,
    )
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("demo_users.id", name="fk_tool_executions_actor_id_demo_users"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_data: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConfirmationChallenge(Base):
    __tablename__ = "confirmation_challenges"
    __table_args__ = (
        UniqueConstraint("actor_id", "idempotency_key", name="uq_confirmation_actor_idempotency"),
        UniqueConstraint("tool_execution_id", name="uq_confirmation_challenges_tool_execution_id"),
        CheckConstraint(
            "target_status in ('active', 'frozen')", name="challenge_target_status_allowed"
        ),
        CheckConstraint(
            "status in ('pending', 'consumed', 'expired', 'cancelled', 'invalidated')",
            name="confirmation_status_allowed",
        ),
        Index("ix_confirmation_challenges_task_id", "task_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "agent_tasks.id",
            name="fk_confirmation_challenges_task_id_agent_tasks",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    tool_execution_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "tool_executions.id",
            name="fk_confirmation_challenges_tool_execution_id_tool_executions",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("demo_users.id", name="fk_confirmation_challenges_actor_id_demo_users"),
        nullable=False,
    )
    card_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cards.id", name="fk_confirmation_challenges_card_id_cards"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(16), nullable=False)
    target_status: Mapped[str] = mapped_column(String(16), nullable=False)
    parameters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    card_version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
