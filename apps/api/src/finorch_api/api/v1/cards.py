import base64
import binascii
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from finorch_api.api.v1.card_schemas import CardListResponse, CardResponse
from finorch_api.application.cards import (
    CardNotFoundError,
    CardView,
    get_card,
    list_cards,
)
from finorch_api.infrastructure.database import get_db_session
from finorch_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(prefix="/cards", tags=["cards"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentDemoActor = Annotated[DemoActor, Depends(get_current_demo_actor)]
CardLimit = Annotated[int, Query(ge=1, le=100)]
CardCursor = Annotated[str | None, Query(max_length=32)]


def _encode_cursor(card_id: UUID) -> str:
    return base64.urlsafe_b64encode(card_id.bytes).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> UUID:
    if len(cursor) > 32:
        raise ValueError("Cursor is too long.")
    padded = cursor + "=" * (-len(cursor) % 4)
    raw = base64.b64decode(padded, altchars=b"-_", validate=True)
    if len(raw) != 16:
        raise ValueError("Cursor has an invalid size.")
    return UUID(bytes=raw)


def _to_response(card: CardView) -> CardResponse:
    return CardResponse(
        id=card.id,
        account_id=card.account_id,
        label=card.label,
        card_suffix=card.card_suffix,
        status=card.status,
        version=card.version,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


@router.get("", response_model=CardListResponse, summary="List the current demo user's cards")
def read_cards(
    session: DatabaseSession,
    actor: CurrentDemoActor,
    limit: CardLimit = 20,
    cursor: CardCursor = None,
) -> CardListResponse:
    after_id = None
    if cursor is not None:
        try:
            after_id = _decode_cursor(cursor)
        except (ValueError, binascii.Error):
            raise HTTPException(status_code=422, detail="Invalid cursor.") from None

    page = list_cards(session, actor_id=actor.user_id, limit=limit, after_id=after_id)
    next_cursor = _encode_cursor(page.items[-1].id) if page.has_more and page.items else None
    return CardListResponse(
        items=[_to_response(card) for card in page.items],
        next_cursor=next_cursor,
    )


@router.get(
    "/{card_id}",
    response_model=CardResponse,
    summary="Get a card belonging to the current demo user",
)
def read_card(
    card_id: UUID,
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> CardResponse:
    try:
        return _to_response(get_card(session, actor_id=actor.user_id, card_id=card_id))
    except CardNotFoundError:
        raise HTTPException(status_code=404, detail="Card not found.") from None
