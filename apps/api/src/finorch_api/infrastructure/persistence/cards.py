from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch_api.infrastructure.models import Account, Card


def list_owned_cards(
    session: Session,
    *,
    actor_id: UUID,
    limit: int,
    after_id: UUID | None,
) -> tuple[list[Card], bool]:
    statement = (
        select(Card)
        .join(Account, Account.id == Card.account_id)
        .where(Account.demo_user_id == actor_id)
        .order_by(Card.id)
    )
    if after_id is not None:
        statement = statement.where(Card.id > after_id)

    rows = list(session.scalars(statement.limit(limit + 1)))
    return rows[:limit], len(rows) > limit


def get_owned_card(session: Session, *, actor_id: UUID, card_id: UUID) -> Card | None:
    statement = (
        select(Card)
        .join(Account, Account.id == Card.account_id)
        .where(Card.id == card_id, Account.demo_user_id == actor_id)
    )
    return session.scalar(statement)
