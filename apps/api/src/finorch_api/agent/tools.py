from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EmptyToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardSuffixInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_suffix: str = Field(
        pattern=r"^\d{4}$", description="The synthetic card's last four digits."
    )


class CardToolItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    account_id: UUID
    label: str
    card_suffix: str
    status: Literal["active", "frozen"]
    version: int = Field(ge=1)


class CardListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CardToolItem]
    next_cursor: str | None = None


class CardGetOutput(CardToolItem):
    pass


class CardChangeProposalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["awaiting_confirmation"]
    confirmation_required: Literal[True]
    challenge_id: UUID
    card_id: UUID
    card_suffix: str
    card_label: str
    current_status: Literal["active", "frozen"]
    target_status: Literal["active", "frozen"]
    card_version: int
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
