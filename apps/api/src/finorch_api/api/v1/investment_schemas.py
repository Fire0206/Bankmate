from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RiskProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_level: int
    risk_label: str


class RiskQuestionOption(BaseModel):
    value: int
    label: str


class RiskQuestion(BaseModel):
    key: str
    title: str
    options: list[RiskQuestionOption]


class RiskQuestionnaireResponse(BaseModel):
    questionnaire_version: str
    questions: list[RiskQuestion]
    notice: str


class RiskAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questionnaire_version: str
    time_horizon: int = Field(ge=1, le=5)
    loss_tolerance: int = Field(ge=1, le=5)
    liquidity_capacity: int = Field(ge=1, le=5)
    investment_experience: int = Field(ge=1, le=5)


class RiskAssessmentResponse(BaseModel):
    id: UUID
    questionnaire_version: str
    score: int
    risk_level: int
    risk_label: str
    assessed_at: datetime


class InvestmentProductResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    name: str
    category: str
    risk_level: int
    minimum_amount_minor: int
    unit_price_minor: int
    annual_yield_bps: int
    term_days: int
    currency: str
    description: str
    suitable: bool


class InvestmentProductListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[InvestmentProductResponse]
    risk_level: int
    risk_label: str


class InvestmentHoldingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    product_id: UUID
    product_name: str
    units_micros: int
    purchase_price_minor: int
    current_price_minor: int
    current_value_minor: int
    estimated_gain_minor: int
    currency: str
    version: int


class InvestmentPortfolioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    cash_balance_minor: int
    invested_value_minor: int
    estimated_gain_minor: int
    total_assets_minor: int
    risk_level: int
    risk_label: str
    holdings: list[InvestmentHoldingResponse]


class InvestmentOrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    order_type: Literal["buy", "redeem"]
    product_id: UUID
    product_name: str
    amount_minor: int
    currency: str
    status: Literal["awaiting_confirmation", "executed", "cancelled", "failed"]
    executed_at: datetime | None
    holding_id: UUID | None


class InvestmentOrderListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[InvestmentOrderResponse]
