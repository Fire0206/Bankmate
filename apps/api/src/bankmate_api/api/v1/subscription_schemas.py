from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    reminder_days_before: int
    last_reminded_charge_at: datetime | None


class SubscriptionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SubscriptionResponse]
    monthly_total_minor: int
    currency: str


class ReminderPreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_before: int = Field(ge=0, le=30)
    expected_version: int = Field(ge=1)


class SubscriptionReminderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: UUID
    merchant: str
    amount_minor: int
    currency: str
    next_charge_at: datetime
    remind_at: datetime
    reminder_days_before: int
    delivered: bool


class SubscriptionReminderListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SubscriptionReminderResponse]
