from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finorch_api.domain.cards import CardStatus


class CardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    account_id: UUID
    label: str
    card_suffix: str = Field(pattern=r"^\d{4}$")
    status: CardStatus
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class CardListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CardResponse]
    next_cursor: str | None = None
