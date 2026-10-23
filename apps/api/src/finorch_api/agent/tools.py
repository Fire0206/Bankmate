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
    status: Literal["active", "frozen", "lost", "replaced"]
    version: int = Field(ge=1)
    replaced_by_card_id: UUID | None = None


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
    current_status: Literal["active", "frozen", "lost", "replaced"]
    target_status: Literal["active", "frozen", "lost", "replaced"]
    card_version: int
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
    resource_type: Literal["card"] = "card"
    resource_id: UUID
    resource_label: str
    resource_version: int = Field(ge=1)


class BillMonthInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str | None = Field(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Calendar month in UTC using YYYY-MM; omit for the current month.",
    )


class BillSummaryInput(BillMonthInput):
    category: str | None = Field(default=None, min_length=1, max_length=48)


class BillTransactionsInput(BillMonthInput):
    category: str | None = Field(default=None, min_length=1, max_length=48)
    merchant: str | None = Field(default=None, min_length=1, max_length=120)


class BillCategoryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    amount_minor: int
    transaction_count: int


class BillTrendOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str
    income_minor: int
    expense_minor: int


class BillTransactionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    direction: Literal["income", "expense"]
    amount_minor: int
    currency: str
    merchant: str
    category: str
    occurred_at: datetime
    anomaly_reason: str | None
    source_card_suffix: str | None


class BillSummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str
    currency: str
    income_minor: int
    expense_minor: int
    net_minor: int
    selected_category: str | None
    selected_category_expense_minor: int | None
    categories: list[BillCategoryOutput]
    trends: list[BillTrendOutput]
    anomalies: list[BillTransactionOutput]


class BillAnnualInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=2000, le=2100, description="Calendar year in UTC, for example 2026.")


class BillAnnualOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    currency: str
    income_minor: int
    expense_minor: int
    net_minor: int
    monthly_totals: list[BillTrendOutput]
    categories: list[BillCategoryOutput]
    top_expense_category: str | None
    anomalies: list[BillTransactionOutput]


class BillTransactionsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str
    items: list[BillTransactionOutput]
    total: int


class BillAnomaliesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str
    items: list[BillTransactionOutput]


class SubscriptionNameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_name: str = Field(min_length=2, max_length=120)


class SubscriptionToolItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    merchant: str
    amount_minor: int
    currency: str
    billing_cycle: Literal["monthly"]
    status: Literal["active", "paused", "cancelled"]
    next_charge_at: datetime
    version: int = Field(ge=1)
    detected_charge_count: int = Field(ge=3)
    reminder_days_before: int = Field(ge=0, le=30)
    last_reminded_charge_at: datetime | None


class SubscriptionListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SubscriptionToolItem]
    monthly_total_minor: int
    currency: str


class SubscriptionReminderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: UUID
    merchant: str
    amount_minor: int
    currency: str
    next_charge_at: datetime
    remind_at: datetime
    reminder_days_before: int = Field(ge=0, le=30)
    delivered: bool


class SubscriptionRemindersOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SubscriptionReminderItem]


class SubscriptionChangeProposalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["awaiting_confirmation"]
    confirmation_required: Literal[True]
    challenge_id: UUID
    subscription_id: UUID
    merchant: str
    current_status: Literal["active", "paused", "cancelled"]
    target_status: Literal["active", "paused", "cancelled"]
    subscription_version: int
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
    resource_type: Literal["subscription"] = "subscription"
    resource_id: UUID
    resource_label: str
    resource_version: int = Field(ge=1)
