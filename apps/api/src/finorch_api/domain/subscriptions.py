import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


class ChargeLike(Protocol):
    id: object
    account_id: object
    direction: str
    amount_minor: int
    currency: str
    merchant: str
    occurred_at: datetime


@dataclass(frozen=True)
class RecurringSubscriptionCandidate:
    account_id: object
    merchant: str
    merchant_key: str
    amount_minor: int
    currency: str
    source_transaction_ids: tuple[str, ...]
    last_charge_at: datetime
    next_charge_at: datetime


class InvalidSubscriptionTransition(ValueError):
    def __init__(self, current: str, requested: str) -> None:
        super().__init__(f"Cannot change subscription from {current} to {requested}.")
        self.current = current
        self.requested = requested


def normalize_merchant(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def transition_subscription_status(current: str, requested: str) -> str:
    allowed = {
        ("active", "paused"),
        ("paused", "active"),
        ("active", "cancelled"),
        ("paused", "cancelled"),
    }
    if (current, requested) not in allowed:
        raise InvalidSubscriptionTransition(current, requested)
    return requested


def detect_recurring_subscriptions(
    transactions: list[ChargeLike], *, minimum_charges: int = 3
) -> tuple[RecurringSubscriptionCandidate, ...]:
    """Identify equal monthly synthetic debits with 25-35 day intervals."""
    grouped: dict[tuple[object, str, int, str], list[ChargeLike]] = {}
    for transaction in transactions:
        if transaction.direction != "expense":
            continue
        merchant_key = normalize_merchant(transaction.merchant)
        if not merchant_key:
            continue
        key = (
            transaction.account_id,
            merchant_key,
            transaction.amount_minor,
            transaction.currency,
        )
        grouped.setdefault(key, []).append(transaction)

    candidates: list[RecurringSubscriptionCandidate] = []
    for (account_id, merchant_key, amount_minor, currency), charges in grouped.items():
        charges.sort(key=lambda item: item.occurred_at)
        recurring: list[ChargeLike] = []
        for charge in charges:
            if recurring:
                interval = _utc(charge.occurred_at) - _utc(recurring[-1].occurred_at)
                if not timedelta(days=25) <= interval <= timedelta(days=35):
                    recurring = [charge]
                    continue
            recurring.append(charge)
        if len(recurring) < minimum_charges:
            continue
        last = _utc(recurring[-1].occurred_at)
        candidates.append(
            RecurringSubscriptionCandidate(
                account_id=account_id,
                merchant=recurring[-1].merchant,
                merchant_key=merchant_key,
                amount_minor=amount_minor,
                currency=currency,
                source_transaction_ids=tuple(str(item.id) for item in recurring),
                last_charge_at=last,
                next_charge_at=last + timedelta(days=30),
            )
        )
    return tuple(sorted(candidates, key=lambda item: (str(item.account_id), item.merchant_key)))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
