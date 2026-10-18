from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
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
        Index("ix_audit_events_actor_id", "actor_id"),
        Index("ix_audit_events_card_occurred_at", "card_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "demo_users.id", name="fk_audit_events_actor_id_demo_users", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    card_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cards.id", name="fk_audit_events_card_id_cards", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(16), nullable=False)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
