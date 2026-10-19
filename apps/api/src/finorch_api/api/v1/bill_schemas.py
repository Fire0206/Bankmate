from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BillTransactionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    account_id: UUID
    direction: Literal["income", "expense"]
    amount_minor: int
    currency: str
    merchant: str
    category: str
    description: str
    occurred_at: datetime
    anomaly_reason: str | None
    source_card_suffix: str | None


class TransactionPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BillTransactionResponse]
    total: int
    offset: int
    limit: int
    next_offset: int | None


class BillCategoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    amount_minor: int
    transaction_count: int


class BillTrendResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str
    income_minor: int
    expense_minor: int


class BillSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str
    currency: str
    income_minor: int
    expense_minor: int
    net_minor: int
    selected_category: str | None
    selected_category_expense_minor: int | None
    categories: list[BillCategoryResponse]
    trends: list[BillTrendResponse]
    anomalies: list[BillTransactionResponse]
