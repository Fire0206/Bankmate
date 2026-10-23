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
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    accounts: Mapped[list["Account"]] = relationship(back_populates="demo_user")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        UniqueConstraint("actor_id", "idempotency_key", name="uq_risk_assessments_actor_key"),
        CheckConstraint("risk_level between 1 and 5", name="risk_assessment_level_allowed"),
        Index("ix_risk_assessments_actor_created", "actor_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "demo_users.id", name="fk_risk_assessments_actor_id_demo_users", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    questionnaire_version: Mapped[str] = mapped_column(String(32), nullable=False)
    answers: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    answers_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
    balance_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default="1970-01-01 00:00:00",
    )
    __mapper_args__ = {"version_id_col": version}

    demo_user: Mapped[DemoUser] = relationship(back_populates="accounts")
    cards: Mapped[list["Card"]] = relationship(back_populates="account")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="account")


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("length(card_suffix) = 4", name="card_suffix_length"),
        CheckConstraint("status in ('active', 'frozen', 'lost')", name="status_allowed"),
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


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="transaction_amount_positive"),
        CheckConstraint("length(currency) = 3", name="transaction_currency_code_length"),
        CheckConstraint("direction in ('income', 'expense')", name="transaction_direction_allowed"),
        CheckConstraint(
            "entry_kind in ('bill', 'transfer', 'investment')",
            name="transaction_entry_kind_allowed",
        ),
        UniqueConstraint("synthetic_ref", name="uq_transactions_synthetic_ref"),
        Index("ix_transactions_account_occurred_at", "account_id", "occurred_at"),
        Index(
            "ix_transactions_account_category_occurred_at", "account_id", "category", "occurred_at"
        ),
        Index(
            "ix_transactions_account_merchant_occurred_at", "account_id", "merchant", "occurred_at"
        ),
        Index("ix_transactions_card_id", "card_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", name="fk_transactions_account_id_accounts", ondelete="RESTRICT"),
        nullable=False,
    )
    card_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cards.id", name="fk_transactions_card_id_cards", ondelete="RESTRICT"),
        nullable=True,
    )
    synthetic_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="bill")
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    account: Mapped[Account] = relationship(back_populates="transactions")


class Payee(Base):
    __tablename__ = "payees"
    __table_args__ = (
        UniqueConstraint("actor_id", "normalized_name", name="uq_payees_actor_name"),
        Index("ix_payees_actor_name", "actor_id", "normalized_name"),
        Index("uq_payees_actor_phone", "actor_id", "phone_number", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("demo_users.id", name="fk_payees_actor_id_demo_users", ondelete="RESTRICT"),
        nullable=False,
    )
    destination_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "accounts.id", name="fk_payees_destination_account_id_accounts", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(80), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(11), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="transfer_amount_positive"),
        CheckConstraint("length(currency) = 3", name="transfer_currency_code_length"),
        CheckConstraint(
            "transfer_type in ('immediate', 'scheduled')", name="transfer_type_allowed"
        ),
        CheckConstraint(
            "status in ('awaiting_confirmation', 'scheduled', 'executed', 'cancelled', 'failed')",
            name="transfer_status_allowed",
        ),
        CheckConstraint("version >= 1", name="transfer_version_positive"),
        CheckConstraint(
            "(transfer_type = 'scheduled' and scheduled_at is not null) or "
            "(transfer_type = 'immediate' and scheduled_at is null)",
            name="transfer_schedule_matches_type",
        ),
        UniqueConstraint("actor_id", "idempotency_key", name="uq_transfers_actor_idempotency"),
        Index("ix_transfers_actor_created_at", "actor_id", "created_at"),
        Index("ix_transfers_status_scheduled_at", "status", "scheduled_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("demo_users.id", name="fk_transfers_actor_id_demo_users", ondelete="RESTRICT"),
        nullable=False,
    )
    source_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "accounts.id", name="fk_transfers_source_account_id_accounts", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    destination_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "accounts.id", name="fk_transfers_destination_account_id_accounts", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    payee_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payees.id", name="fk_transfers_payee_id_payees", ondelete="RESTRICT"),
        nullable=False,
    )
    payee_name: Mapped[str] = mapped_column(String(80), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transfer_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    __mapper_args__ = {"version_id_col": version}


class SplitBill(Base):
    __tablename__ = "split_bills"
    __table_args__ = (
        CheckConstraint("total_amount_minor > 0", name="split_bill_amount_positive"),
        CheckConstraint("length(currency) = 3", name="split_bill_currency_code_length"),
        CheckConstraint("participant_count between 2 and 11", name="split_bill_count_allowed"),
        CheckConstraint(
            "status in ('awaiting_confirmation', 'open', 'settled', 'cancelled', 'failed')",
            name="split_bill_status_allowed",
        ),
        CheckConstraint("version >= 1", name="split_bill_version_positive"),
        UniqueConstraint("actor_id", "idempotency_key", name="uq_split_bills_actor_idempotency"),
        Index("ix_split_bills_actor_created_at", "actor_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("demo_users.id", name="fk_split_bills_actor_id_demo_users", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", name="fk_split_bills_account_id_accounts", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    __mapper_args__ = {"version_id_col": version}


class SplitParticipant(Base):
    __tablename__ = "split_participants"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="split_participant_amount_positive"),
        CheckConstraint(
            "status in ('organizer_paid', 'pending', 'paid')",
            name="split_participant_status_allowed",
        ),
        UniqueConstraint("split_bill_id", "sequence", name="uq_split_participants_sequence"),
        Index("ix_split_participants_split_bill_id", "split_bill_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    split_bill_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "split_bills.id",
            name="fk_split_participants_split_bill_id_split_bills",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvestmentProduct(Base):
    __tablename__ = "investment_products"
    __table_args__ = (
        CheckConstraint("risk_level between 1 and 5", name="investment_product_risk_allowed"),
        CheckConstraint("minimum_amount_minor > 0", name="investment_product_minimum_positive"),
        CheckConstraint("unit_price_minor > 0", name="investment_product_price_positive"),
        CheckConstraint(
            "annual_yield_bps between -10000 and 100000", name="investment_product_yield_allowed"
        ),
        CheckConstraint("term_days >= 0", name="investment_product_term_nonnegative"),
        CheckConstraint("length(currency) = 3", name="investment_product_currency_code_length"),
        UniqueConstraint("code", name="uq_investment_products_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    annual_yield_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InvestmentHolding(Base):
    __tablename__ = "investment_holdings"
    __table_args__ = (
        CheckConstraint("units_micros >= 0", name="investment_holding_units_nonnegative"),
        CheckConstraint("purchase_price_minor > 0", name="investment_holding_price_positive"),
        CheckConstraint("version >= 1", name="investment_holding_version_positive"),
        Index("ix_investment_holdings_actor_account", "actor_id", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "demo_users.id", name="fk_investment_holdings_actor_id_demo_users", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "accounts.id", name="fk_investment_holdings_account_id_accounts", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "investment_products.id",
            name="fk_investment_holdings_product_id_investment_products",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    units_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purchase_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    __mapper_args__ = {"version_id_col": version}


class InvestmentOrder(Base):
    __tablename__ = "investment_orders"
    __table_args__ = (
        CheckConstraint("order_type in ('buy', 'redeem')", name="investment_order_type_allowed"),
        CheckConstraint("amount_minor > 0", name="investment_order_amount_positive"),
        CheckConstraint("units_micros >= 0", name="investment_order_units_nonnegative"),
        CheckConstraint(
            "status in ('awaiting_confirmation', 'executed', 'cancelled', 'failed')",
            name="investment_order_status_allowed",
        ),
        CheckConstraint("version >= 1", name="investment_order_version_positive"),
        UniqueConstraint(
            "actor_id", "idempotency_key", name="uq_investment_orders_actor_idempotency"
        ),
        Index("ix_investment_orders_actor_created_at", "actor_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "demo_users.id", name="fk_investment_orders_actor_id_demo_users", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "accounts.id", name="fk_investment_orders_account_id_accounts", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "investment_products.id",
            name="fk_investment_orders_product_id_investment_products",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    holding_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "investment_holdings.id",
            name="fk_investment_orders_holding_id_investment_holdings",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    order_type: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    units_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    __mapper_args__ = {"version_id_col": version}


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="subscription_amount_positive"),
        CheckConstraint("length(currency) = 3", name="subscription_currency_code_length"),
        CheckConstraint("billing_cycle = 'monthly'", name="subscription_billing_cycle_allowed"),
        CheckConstraint(
            "status in ('active', 'paused', 'cancelled')", name="subscription_status_allowed"
        ),
        CheckConstraint("version >= 1", name="subscription_version_positive"),
        CheckConstraint(
            "reminder_days_before between 0 and 30", name="subscription_reminder_days_allowed"
        ),
        UniqueConstraint("account_id", "merchant_key", name="uq_subscriptions_account_merchant"),
        Index("ix_subscriptions_account_status", "account_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", name="fk_subscriptions_account_id_accounts", ondelete="RESTRICT"),
        nullable=False,
    )
    merchant_key: Mapped[str] = mapped_column(String(120), nullable=False)
    merchant: Mapped[str] = mapped_column(String(120), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(16), nullable=False, default="monthly")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    next_charge_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reminder_days_before: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_reminded_charge_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_transaction_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    __mapper_args__ = {"version_id_col": version}

    account: Mapped[Account] = relationship(back_populates="subscriptions")


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


class StrongVerification(Base):
    __tablename__ = "strong_verifications"
    __table_args__ = (
        CheckConstraint("attempts >= 0 and attempts <= 5", name="verification_attempts_range"),
        CheckConstraint(
            "status in ('pending', 'verified', 'consumed', 'locked', 'expired', 'invalidated')",
            name="verification_status_allowed",
        ),
        UniqueConstraint("confirmation_id", name="uq_verification_confirmation"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    confirmation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("confirmation_challenges.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("demo_users.id"),
        nullable=False,
    )
    binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ConfirmationChallenge(Base):
    __tablename__ = "confirmation_challenges"
    __table_args__ = (
        UniqueConstraint("actor_id", "idempotency_key", name="uq_confirmation_actor_idempotency"),
        UniqueConstraint("tool_execution_id", name="uq_confirmation_challenges_tool_execution_id"),
        CheckConstraint(
            "target_status in ('active', 'frozen', 'paused', 'cancelled', 'executed', "
            "'scheduled', 'open', 'settled', 'lost')",
            name="challenge_target_status_allowed",
        ),
        CheckConstraint(
            "(case when card_id is not null then 1 else 0 end + "
            "case when subscription_id is not null then 1 else 0 end + "
            "case when transfer_id is not null then 1 else 0 end + "
            "case when split_bill_id is not null then 1 else 0 end + "
            "case when investment_order_id is not null then 1 else 0 end) = 1",
            name="challenge_single_resource",
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
    card_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cards.id", name="fk_confirmation_challenges_card_id_cards"),
        nullable=True,
    )
    subscription_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "subscriptions.id",
            name="fk_confirmation_challenges_subscription_id_subscriptions",
        ),
        nullable=True,
    )
    transfer_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transfers.id", name="fk_confirmation_challenges_transfer_id_transfers"),
        nullable=True,
    )
    split_bill_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("split_bills.id", name="fk_confirmation_challenges_split_bill_id_split_bills"),
        nullable=True,
    )
    investment_order_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "investment_orders.id",
            name="fk_confirmation_challenges_investment_order_id_investment_orders",
        ),
        nullable=True,
    )
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(16), nullable=False)
    target_status: Mapped[str] = mapped_column(String(16), nullable=False)
    parameters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    card_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscription_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transfer_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    split_bill_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    investment_order_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
