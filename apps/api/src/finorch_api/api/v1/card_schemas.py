from datetime import datetime
from typing import Literal
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
    single_limit_minor: int = Field(gt=0)
    daily_limit_minor: int = Field(gt=0)
    online_enabled: bool
    replaced_by_card_id: UUID | None
    created_at: datetime
    updated_at: datetime


class CardListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CardResponse]
    next_cursor: str | None = None


class CardApplicationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    account_id: UUID
    account_label: str
    label: str
    status: Literal["pending_confirmation", "submitted", "approved", "rejected", "cancelled"]
    issued_card_id: UUID | None
    issued_card_suffix: str | None
    version: int
    created_at: datetime
    reviewed_at: datetime | None


class CardApplicationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CardApplicationResponse]
