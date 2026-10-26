"""Shared deterministic availability rules for simulated account debits."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finorch_api.infrastructure.models import Account, FundsReservation


def held_amount_minor(
    session: Session, *, account_id: UUID, exclude_reservation_id: UUID | None = None
) -> int:
    statement = select(func.coalesce(func.sum(FundsReservation.held_minor), 0)).where(
        FundsReservation.account_id == account_id,
        FundsReservation.status == "held",
    )
    if exclude_reservation_id is not None:
        statement = statement.where(FundsReservation.id != exclude_reservation_id)
    return int(session.scalar(statement) or 0)


def available_balance_minor(
    session: Session, *, account: Account, exclude_reservation_id: UUID | None = None
) -> int:
    """Return spendable funds; a held reservation remains part of total account assets."""
    return account.balance_minor - held_amount_minor(
        session, account_id=account.id, exclude_reservation_id=exclude_reservation_id
    )
