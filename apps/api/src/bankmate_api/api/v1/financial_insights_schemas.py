from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PaydayPlanPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_name: str = Field(min_length=1, max_length=80)
    transfer_amount_minor: int = Field(gt=0, le=10_000_000_000, strict=True)
    reserve_amount_minor: int = Field(ge=0, le=10_000_000_000, strict=True)
    source_account_label: str | None = Field(default=None, max_length=80)
    month: str | None = Field(default=None, pattern=r"^20\d{2}-(0[1-9]|1[0-2])$")

    @field_validator("recipient_name")
    @classmethod
    def recipient_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Recipient name must not be blank.")
        return normalized


class PaydayPlanPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_label: str
    currency: str
    month: str
    account_balance_minor: int
    available_balance_minor: int
    monthly_income_minor: int
    monthly_expense_minor: int
    recipient_name: str
    transfer_amount_minor: int
    reserve_amount_minor: int
    remaining_after_transfer_minor: int
    investment_budget_minor: int
    reserve_shortfall_minor: int


class FinancialRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: Literal["bill_review", "cashflow_review", "subscription_review"]
    priority: Literal["high", "medium", "low"]
    title: str
    explanation: str
    amount_minor: int | None
    currency: str
    source_transaction_ids: list[UUID]


class FinancialRecommendationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str
    generated_at: datetime
    items: list[FinancialRecommendationResponse]
