from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import randbelow
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from finorch_api.application.transactions import write_transaction
from finorch_api.domain.cards import CardStatus, InvalidCardTransition, transition_card_status
from finorch_api.infrastructure.models import Account, AuditEvent, Card
from finorch_api.infrastructure.persistence.cards import (
    get_owned_card,
    list_owned_cards,
)


class CardNotFoundError(LookupError):
    """Raised when a card is absent or does not belong to the actor."""


class CardWriteConflictError(RuntimeError):
    """Raised when a concurrent change made the card version stale."""


@dataclass(frozen=True)
class CardView:
    id: UUID
    account_id: UUID
    label: str
    card_suffix: str
    status: CardStatus
    version: int
    single_limit_minor: int
    daily_limit_minor: int
    online_enabled: bool
    replaced_by_card_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CardPage:
    items: tuple[CardView, ...]
    has_more: bool


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_view(card: Card) -> CardView:
    return CardView(
        id=card.id,
        account_id=card.account_id,
        label=card.label,
        card_suffix=card.card_suffix,
        status=card.status,
        version=card.version,
        single_limit_minor=card.single_limit_minor,
        daily_limit_minor=card.daily_limit_minor,
        online_enabled=card.online_enabled,
        replaced_by_card_id=card.replaced_by_card_id,
        created_at=_as_utc(card.created_at),
        updated_at=_as_utc(card.updated_at),
    )


def list_cards(
    session: Session,
    *,
    actor_id: UUID,
    limit: int,
    after_id: UUID | None = None,
) -> CardPage:
    cards, has_more = list_owned_cards(
        session,
        actor_id=actor_id,
        limit=limit,
        after_id=after_id,
    )
    return CardPage(items=tuple(_to_view(card) for card in cards), has_more=has_more)


def get_card(session: Session, *, actor_id: UUID, card_id: UUID) -> CardView:
    card = get_owned_card(session, actor_id=actor_id, card_id=card_id)
    if card is None:
        raise CardNotFoundError
    return _to_view(card)


def _change_card_status(
    session: Session,
    *,
    actor_id: UUID,
    card_id: UUID,
    target_status: CardStatus,
    request_id: str,
    task_id: UUID | None = None,
    tool_execution_id: UUID | None = None,
) -> CardView:
    try:
        with write_transaction(session):
            card = get_owned_card(session, actor_id=actor_id, card_id=card_id)
            if card is None:
                raise CardNotFoundError

            previous_status = card.status
            card.status = transition_card_status(previous_status, target_status)
            session.flush()
            session.add(
                AuditEvent(
                    actor_id=actor_id,
                    card_id=card.id,
                    event_type="card.status_changed",
                    resource_type="card",
                    resource_id=card.id,
                    previous_status=previous_status.value,
                    new_status=card.status.value,
                    resource_version=card.version,
                    request_id=request_id,
                    task_id=task_id,
                    tool_execution_id=tool_execution_id,
                    outcome="succeeded",
                    before_state={"status": previous_status.value, "version": card.version - 1},
                    after_state={"status": card.status.value, "version": card.version},
                )
            )
            session.flush()
            result = _to_view(card)
    except StaleDataError as exc:
        raise CardWriteConflictError("Card changed during this operation.") from exc
    return result


def freeze_card(
    session: Session,
    *,
    actor_id: UUID,
    card_id: UUID,
    request_id: str,
    task_id: UUID | None = None,
    tool_execution_id: UUID | None = None,
) -> CardView:
    return _change_card_status(
        session,
        actor_id=actor_id,
        card_id=card_id,
        target_status=CardStatus.FROZEN,
        request_id=request_id,
        task_id=task_id,
        tool_execution_id=tool_execution_id,
    )


def unfreeze_card(
    session: Session,
    *,
    actor_id: UUID,
    card_id: UUID,
    request_id: str,
    task_id: UUID | None = None,
    tool_execution_id: UUID | None = None,
) -> CardView:
    return _change_card_status(
        session,
        actor_id=actor_id,
        card_id=card_id,
        target_status=CardStatus.ACTIVE,
        request_id=request_id,
        task_id=task_id,
        tool_execution_id=tool_execution_id,
    )


def report_card_lost(
    session: Session,
    *,
    actor_id: UUID,
    card_id: UUID,
    request_id: str,
    task_id: UUID | None = None,
    tool_execution_id: UUID | None = None,
) -> CardView:
    """Mark a synthetic card lost; this state cannot be reversed by unfreeze."""
    return _change_card_status(
        session,
        actor_id=actor_id,
        card_id=card_id,
        target_status=CardStatus.LOST,
        request_id=request_id,
        task_id=task_id,
        tool_execution_id=tool_execution_id,
    )


def replace_lost_card(
    session: Session,
    *,
    actor_id: UUID,
    card_id: UUID,
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID,
) -> tuple[CardView, CardView]:
    """Close a lost demo card and issue a new synthetic debit card atomically."""
    with write_transaction(session):
        old = get_owned_card(session, actor_id=actor_id, card_id=card_id)
        if old is None:
            raise CardNotFoundError
        transition_card_status(old.status, CardStatus.REPLACED)
        suffixes = set(
            session.scalars(
                select(Card.card_suffix)
                .join(Account, Card.account_id == Account.id)
                .where(Account.demo_user_id == actor_id)
            )
        )
        suffix = next(
            (
                candidate
                for _ in range(100)
                if (candidate := f"{randbelow(10000):04d}") not in suffixes
            ),
            None,
        )
        if suffix is None:
            raise CardWriteConflictError("Could not assign a unique demo card suffix.")
        new = Card(
            id=uuid4(),
            account_id=old.account_id,
            label=f"{old.label}（补发）"[:80],
            card_suffix=suffix,
            status=CardStatus.ACTIVE,
        )
        session.add(new)
        session.flush()
        before_version = old.version
        old.status = CardStatus.REPLACED
        old.replaced_by_card_id = new.id
        session.flush()
        session.add(
            AuditEvent(
                actor_id=actor_id,
                card_id=old.id,
                event_type="card.replaced",
                resource_type="card",
                resource_id=old.id,
                resource_version=old.version,
                request_id=request_id,
                task_id=task_id,
                tool_execution_id=tool_execution_id,
                outcome="succeeded",
                before_state={"status": "lost", "version": before_version},
                after_state={
                    "status": "replaced",
                    "version": old.version,
                    "new_card_id": str(new.id),
                    "new_card_suffix": new.card_suffix,
                },
            )
        )
        session.flush()
        return _to_view(old), _to_view(new)


__all__ = [
    "CardNotFoundError",
    "CardPage",
    "CardView",
    "CardWriteConflictError",
    "InvalidCardTransition",
    "freeze_card",
    "get_card",
    "list_cards",
    "report_card_lost",
    "replace_lost_card",
    "unfreeze_card",
]
