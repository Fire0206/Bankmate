from uuid import UUID

from sqlalchemy.orm import Session

from finorch_api.domain.cards import CardStatus
from finorch_api.infrastructure.database import Base
from finorch_api.infrastructure.models import Account, Card, DemoUser
from finorch_api.security.demo_identity import DEMO_USER_ONE_ID, DEMO_USER_TWO_ID

DATASET_VERSION = "phase1a-v1"

_USERS = (
    (DEMO_USER_ONE_ID, "Demo User One"),
    (DEMO_USER_TWO_ID, "Demo User Two"),
)

_ACCOUNTS = (
    (
        UUID("10000000-0000-4000-8000-000000000001"),
        DEMO_USER_ONE_ID,
        "Everyday account",
        "CNY",
        1_250_000,
    ),
    (
        UUID("10000000-0000-4000-8000-000000000002"),
        DEMO_USER_ONE_ID,
        "Savings account",
        "CNY",
        8_000_000,
    ),
    (
        UUID("10000000-0000-4000-8000-000000000003"),
        DEMO_USER_TWO_ID,
        "Everyday account",
        "CNY",
        642_500,
    ),
)

_CARDS = (
    (
        UUID("20000000-0000-4000-8000-000000000001"),
        UUID("10000000-0000-4000-8000-000000000001"),
        "Everyday debit",
        "1042",
        CardStatus.ACTIVE,
    ),
    (
        UUID("20000000-0000-4000-8000-000000000002"),
        UUID("10000000-0000-4000-8000-000000000002"),
        "Savings debit",
        "4318",
        CardStatus.FROZEN,
    ),
    (
        UUID("20000000-0000-4000-8000-000000000003"),
        UUID("10000000-0000-4000-8000-000000000003"),
        "Travel debit",
        "2729",
        CardStatus.ACTIVE,
    ),
)


def _add_missing(session: Session, model: type[Base], entity_id: UUID, **values: object) -> None:
    if session.get(model, entity_id) is None:
        session.add(model(id=entity_id, **values))


def seed_demo_data(session: Session) -> None:
    """Insert missing deterministic fixtures; the caller owns the transaction."""
    for user_id, display_name in _USERS:
        _add_missing(
            session,
            DemoUser,
            user_id,
            display_name=display_name,
            dataset_version=DATASET_VERSION,
        )
    session.flush()

    for account_id, user_id, label, currency, opening_balance_minor in _ACCOUNTS:
        _add_missing(
            session,
            Account,
            account_id,
            demo_user_id=user_id,
            label=label,
            currency=currency,
            opening_balance_minor=opening_balance_minor,
        )
    session.flush()

    for card_id, account_id, label, suffix, status in _CARDS:
        _add_missing(
            session,
            Card,
            card_id,
            account_id=account_id,
            label=label,
            card_suffix=suffix,
            status=status,
            version=1,
        )
    session.flush()
