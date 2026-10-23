from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from finorch_api.application.transactions import write_transaction
from finorch_api.domain.subscriptions import (
    InvalidSubscriptionTransition,
    normalize_merchant,
    transition_subscription_status,
)
from finorch_api.infrastructure.models import Account, AuditEvent, Subscription, utc_now


class SubscriptionNotFoundError(LookupError):
    """The subscription is absent or does not belong to the actor."""


class SubscriptionAmbiguousError(LookupError):
    """The supplied merchant name matches more than one owned subscription."""


class SubscriptionWriteConflictError(RuntimeError):
    """A concurrent subscription update made the confirmation stale."""


@dataclass(frozen=True)
class SubscriptionView:
    id: UUID
    account_id: UUID
    merchant: str
    amount_minor: int
    currency: str
    billing_cycle: str
    status: str
    next_charge_at: datetime
    version: int
    detected_charge_count: int
    reminder_days_before: int
    last_reminded_charge_at: datetime | None


@dataclass(frozen=True)
class SubscriptionListView:
    items: tuple[SubscriptionView, ...]
    monthly_total_minor: int
    currency: str


@dataclass(frozen=True)
class SubscriptionReminderView:
    subscription_id: UUID
    merchant: str
    amount_minor: int
    currency: str
    next_charge_at: datetime
    remind_at: datetime
    reminder_days_before: int
    delivered: bool


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _view(value: Subscription) -> SubscriptionView:
    return SubscriptionView(
        id=value.id,
        account_id=value.account_id,
        merchant=value.merchant,
        amount_minor=value.amount_minor,
        currency=value.currency,
        billing_cycle=value.billing_cycle,
        status=value.status,
        next_charge_at=_utc(value.next_charge_at),
        version=value.version,
        detected_charge_count=len(value.source_transaction_ids),
        reminder_days_before=value.reminder_days_before,
        last_reminded_charge_at=(
            _utc(value.last_reminded_charge_at) if value.last_reminded_charge_at else None
        ),
    )


def _owned_statement(actor_id: UUID):
    return (
        select(Subscription)
        .join(Account, Account.id == Subscription.account_id)
        .where(Account.demo_user_id == actor_id)
    )


def get_owned_subscription(
    session: Session, *, actor_id: UUID, subscription_id: UUID
) -> Subscription | None:
    return session.scalar(_owned_statement(actor_id).where(Subscription.id == subscription_id))


def list_subscriptions(session: Session, *, actor_id: UUID) -> SubscriptionListView:
    rows = list(
        session.scalars(
            _owned_statement(actor_id).order_by(
                Subscription.status, Subscription.next_charge_at, Subscription.merchant
            )
        )
    )
    active_total = sum(item.amount_minor for item in rows if item.status == "active")
    return SubscriptionListView(
        items=tuple(_view(item) for item in rows),
        monthly_total_minor=active_total,
        currency="CNY",
    )


def list_subscription_reminders(
    session: Session, *, actor_id: UUID, now: datetime | None = None
) -> tuple[SubscriptionReminderView, ...]:
    """Return upcoming active synthetic renewals; reading does not emit a notice."""
    at = _utc(now or utc_now())
    rows = session.scalars(_owned_statement(actor_id).where(Subscription.status == "active"))
    result = []
    for item in rows:
        charge_at = _utc(item.next_charge_at)
        if charge_at < at or charge_at > at + timedelta(days=30):
            continue
        result.append(
            SubscriptionReminderView(
                subscription_id=item.id,
                merchant=item.merchant,
                amount_minor=item.amount_minor,
                currency=item.currency,
                next_charge_at=charge_at,
                remind_at=charge_at - timedelta(days=item.reminder_days_before),
                reminder_days_before=item.reminder_days_before,
                delivered=(
                    item.last_reminded_charge_at is not None
                    and _utc(item.last_reminded_charge_at) == charge_at
                ),
            )
        )
    return tuple(sorted(result, key=lambda value: (value.next_charge_at, value.merchant)))


def generate_due_subscription_reminders(
    session: Session, *, actor_id: UUID, request_id: str, now: datetime | None = None
) -> tuple[SubscriptionReminderView, ...]:
    """Record one local notice per billing cycle under the shared write transaction."""
    at = _utc(now or utc_now())
    created = []
    with write_transaction(session, immediate=True):
        for reminder in list_subscription_reminders(session, actor_id=actor_id, now=at):
            if reminder.delivered or at < reminder.remind_at:
                continue
            subscription = get_owned_subscription(
                session, actor_id=actor_id, subscription_id=reminder.subscription_id
            )
            if subscription is None or subscription.status != "active":
                continue
            subscription.last_reminded_charge_at = reminder.next_charge_at
            session.flush()
            session.add(
                AuditEvent(
                    actor_id=actor_id,
                    event_type="subscription.renewal_reminder_created",
                    resource_type="subscription",
                    resource_id=subscription.id,
                    resource_version=subscription.version,
                    request_id=request_id,
                    outcome="succeeded",
                    after_state={
                        "billing_at": reminder.next_charge_at.isoformat(),
                        "reminder_days_before": reminder.reminder_days_before,
                        "delivery": "in_app",
                    },
                    occurred_at=at,
                )
            )
            created.append(replace(reminder, delivered=True))
        session.flush()
    return tuple(created)


def set_subscription_reminder_days(
    session: Session,
    *,
    actor_id: UUID,
    subscription_id: UUID,
    days_before: int,
    expected_version: int,
    request_id: str,
) -> SubscriptionView:
    if type(days_before) is not int or not 0 <= days_before <= 30:
        raise ValueError("Reminder lead time must be between 0 and 30 days.")
    try:
        with write_transaction(session, immediate=True):
            subscription = get_owned_subscription(
                session, actor_id=actor_id, subscription_id=subscription_id
            )
            if subscription is None:
                raise SubscriptionNotFoundError
            if subscription.reminder_days_before == days_before:
                return _view(subscription)
            if subscription.version != expected_version:
                raise SubscriptionWriteConflictError("Subscription changed since it was read.")
            before = subscription.reminder_days_before
            subscription.reminder_days_before = days_before
            session.flush()
            session.add(
                AuditEvent(
                    actor_id=actor_id,
                    event_type="subscription.reminder_preference_changed",
                    resource_type="subscription",
                    resource_id=subscription.id,
                    resource_version=subscription.version,
                    request_id=request_id,
                    outcome="succeeded",
                    before_state={"days_before": before},
                    after_state={"days_before": days_before},
                    occurred_at=utc_now(),
                )
            )
            session.flush()
            return _view(subscription)
    except StaleDataError as exc:
        raise SubscriptionWriteConflictError("Subscription changed during the operation.") from exc


def find_owned_subscription(
    session: Session, *, actor_id: UUID, merchant_name: str
) -> Subscription:
    target = normalize_merchant(merchant_name)
    if not target:
        raise SubscriptionNotFoundError
    rows = list(session.scalars(_owned_statement(actor_id)))
    matches = [item for item in rows if target in normalize_merchant(item.merchant)]
    if not matches:
        raise SubscriptionNotFoundError
    if len(matches) > 1:
        raise SubscriptionAmbiguousError
    return matches[0]


def change_subscription_status(
    session: Session,
    *,
    actor_id: UUID,
    subscription_id: UUID,
    target_status: str,
    request_id: str,
    task_id: UUID | None = None,
    tool_execution_id: UUID | None = None,
) -> SubscriptionView:
    try:
        with write_transaction(session):
            subscription = get_owned_subscription(
                session, actor_id=actor_id, subscription_id=subscription_id
            )
            if subscription is None:
                raise SubscriptionNotFoundError
            previous_status = subscription.status
            previous_version = subscription.version
            subscription.status = transition_subscription_status(previous_status, target_status)
            session.flush()
            session.add(
                AuditEvent(
                    actor_id=actor_id,
                    event_type="subscription.status_changed",
                    resource_type="subscription",
                    resource_id=subscription.id,
                    resource_version=subscription.version,
                    request_id=request_id,
                    task_id=task_id,
                    tool_execution_id=tool_execution_id,
                    outcome="succeeded",
                    before_state={"status": previous_status, "version": previous_version},
                    after_state={"status": subscription.status, "version": subscription.version},
                    occurred_at=utc_now(),
                )
            )
            session.flush()
            result = _view(subscription)
    except StaleDataError as exc:
        raise SubscriptionWriteConflictError("Subscription changed during the operation.") from exc
    return result


__all__ = [
    "InvalidSubscriptionTransition",
    "SubscriptionAmbiguousError",
    "SubscriptionListView",
    "SubscriptionReminderView",
    "SubscriptionNotFoundError",
    "SubscriptionView",
    "SubscriptionWriteConflictError",
    "change_subscription_status",
    "find_owned_subscription",
    "get_owned_subscription",
    "list_subscriptions",
    "list_subscription_reminders",
    "generate_due_subscription_reminders",
    "set_subscription_reminder_days",
]
