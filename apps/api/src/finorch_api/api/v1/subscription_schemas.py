from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    account_id: UUID
    merchant: str
    amount_minor: int
    currency: str
    billing_cycle: Literal["monthly"]
    status: Literal["active", "paused", "cancelled"]
    next_charge_at: datetime
    version: int
    detected_charge_count: int


class SubscriptionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SubscriptionResponse]
    monthly_total_minor: int
    currency: str
