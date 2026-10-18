from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from finorch_api.domain.cards import CardStatus, InvalidCardTransition, transition_card_status
from finorch_api.infrastructure.models import AuditEvent, Card
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
) -> CardView:
    try:
        with session.begin():
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
                    previous_status=previous_status.value,
                    new_status=card.status.value,
                    resource_version=card.version,
                    request_id=request_id,
                )
            )
            session.flush()
            result = _to_view(card)
    except StaleDataError as exc:
        raise CardWriteConflictError("Card changed during this operation.") from exc
    return result


def freeze_card(session: Session, *, actor_id: UUID, card_id: UUID, request_id: str) -> CardView:
    return _change_card_status(
        session,
        actor_id=actor_id,
        card_id=card_id,
        target_status=CardStatus.FROZEN,
        request_id=request_id,
    )


def unfreeze_card(session: Session, *, actor_id: UUID, card_id: UUID, request_id: str) -> CardView:
    return _change_card_status(
        session,
        actor_id=actor_id,
        card_id=card_id,
        target_status=CardStatus.ACTIVE,
        request_id=request_id,
    )


__all__ = [
    "CardNotFoundError",
    "CardPage",
    "CardView",
    "CardWriteConflictError",
    "InvalidCardTransition",
    "freeze_card",
    "get_card",
    "list_cards",
    "unfreeze_card",
]
