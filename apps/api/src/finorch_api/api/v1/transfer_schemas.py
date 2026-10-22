from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AccountBalanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    label: str
    currency: str
    balance_minor: int


class AccountBalanceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AccountBalanceResponse]


class PayeeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=80)
    destination_account_id: UUID
    phone_number: str | None = Field(default=None, pattern=r"^1[3-9]\d{9}$")


class PayeeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    display_name: str
    destination_account_id: UUID
    destination_account_label: str
    currency: str
    phone_masked: str | None


class PayeeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PayeeResponse]


class TransferResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_account_id: UUID
    source_account_label: str
    destination_account_id: UUID
    payee_name: str
    remark: str | None
    amount_minor: int
    currency: str
    transfer_type: Literal["immediate", "scheduled"]
    status: Literal["awaiting_confirmation", "scheduled", "executed", "cancelled", "failed"]
    scheduled_at: datetime | None
    executed_at: datetime | None
    version: int


class TransferListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TransferResponse]


class SplitParticipantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    display_name: str
    amount_minor: int
    status: Literal["organizer_paid", "pending", "paid"]


class SplitBillResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    total_amount_minor: int
    currency: str
    participant_count: int
    status: Literal["awaiting_confirmation", "open", "settled", "cancelled", "failed"]
    participants: list[SplitParticipantResponse]
    version: int


class SplitBillListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SplitBillResponse]


class SimulatedTransfersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executed_count: int
    items: list[TransferResponse]
