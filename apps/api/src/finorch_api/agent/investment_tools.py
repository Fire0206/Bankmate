from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finorch_api.agent.context import ToolCallContext
from finorch_api.agent.runtime import ToolSpec
from finorch_api.application.errors import BankingRuleError
from finorch_api.application.investments import (
    get_portfolio,
    get_risk_profile,
    list_orders,
    list_products,
    propose_purchase,
    propose_redemption,
)


class InvestmentEmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, max_length=48)
    maximum_risk_level: int | None = Field(default=None, ge=1, le=5)


class InvestmentCompareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_names: list[str] = Field(min_length=2, max_length=5)


class InvestmentPurchaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(min_length=1, max_length=100)
    amount_minor: int = Field(gt=0, le=10_000_000_000)
    account_label: str | None = Field(default=None, max_length=80)


class InvestmentRedemptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(min_length=1, max_length=100)
    amount_minor: int | None = Field(default=None, gt=0, le=10_000_000_000)
    holding_id: UUID | None = None


class ProductToolItem(BaseModel):
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


class ProductsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProductToolItem]
    risk_level: int
    risk_label: str


class HoldingToolItem(BaseModel):
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


class PortfolioOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    cash_balance_minor: int
    invested_value_minor: int
    estimated_gain_minor: int
    total_assets_minor: int
    risk_level: int
    risk_label: str
    holdings: list[HoldingToolItem]


class OrderToolItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    order_type: Literal["buy", "redeem"]
    product_id: UUID
    product_name: str
    amount_minor: int
    currency: str
    status: Literal["awaiting_confirmation", "executed", "cancelled", "failed"]
    executed_at: str | None
    holding_id: UUID | None


class OrdersOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OrderToolItem]


class InvestmentProposalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["awaiting_confirmation"]
    confirmation_required: Literal[True]
    challenge_id: UUID
    order_id: UUID
    order_type: Literal["buy", "redeem"]
    product_id: UUID
    product_name: str
    account_label: str
    amount_minor: int
    currency: str
    units_micros: int
    risk_level: int
    current_status: str
    target_status: str
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
    resource_type: Literal["investment_order"]
    resource_id: UUID
    resource_label: str
    resource_version: int


class InvestmentRiskProfileOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_level: int
    risk_label: str
    source: Literal["synthetic_demo_profile"]


def investment_tool_specs() -> tuple[ToolSpec, ...]:
    def get_products(arguments: BaseModel, context: ToolCallContext) -> ProductsOutput:
        values = ProductQueryInput.model_validate(arguments)
        items = list_products(
            context.session,
            actor_id=context.actor_id,
            category=values.category,
            maximum_risk_level=values.maximum_risk_level,
        )
        risk_level, risk_label = get_risk_profile(context.session, actor_id=context.actor_id)
        return ProductsOutput(
            items=[ProductToolItem.model_validate(item.__dict__) for item in items],
            risk_level=risk_level,
            risk_label=risk_label,
        )

    def compare_products(arguments: BaseModel, context: ToolCallContext) -> ProductsOutput:
        values = InvestmentCompareInput.model_validate(arguments)
        all_items = list_products(context.session, actor_id=context.actor_id)
        selected = [
            next(
                (
                    item
                    for item in all_items
                    if item.name.casefold() == name.strip().casefold()
                    or item.code.casefold() == name.strip().casefold()
                ),
                None,
            )
            for name in values.product_names
        ]
        if any(item is None for item in selected):
            raise BankingRuleError("product_not_found", "有产品名称未匹配到模拟产品目录。")
        risk_level, risk_label = get_risk_profile(context.session, actor_id=context.actor_id)
        return ProductsOutput(
            items=[ProductToolItem.model_validate(item.__dict__) for item in selected if item],
            risk_level=risk_level,
            risk_label=risk_label,
        )

    def profile_handler(
        _arguments: BaseModel, context: ToolCallContext
    ) -> InvestmentRiskProfileOutput:
        risk_level, risk_label = get_risk_profile(context.session, actor_id=context.actor_id)
        return InvestmentRiskProfileOutput(
            risk_level=risk_level,
            risk_label=risk_label,
            source="synthetic_demo_profile",
        )

    def portfolio_handler(_arguments: BaseModel, context: ToolCallContext) -> PortfolioOutput:
        value = get_portfolio(context.session, actor_id=context.actor_id)
        return PortfolioOutput(
            currency=value.currency,
            cash_balance_minor=value.cash_balance_minor,
            invested_value_minor=value.invested_value_minor,
            estimated_gain_minor=value.estimated_gain_minor,
            total_assets_minor=value.total_assets_minor,
            risk_level=value.risk_level,
            risk_label=value.risk_label,
            holdings=[
                HoldingToolItem(
                    id=holding.id,
                    product_id=holding.product_id,
                    product_name=holding.product_name,
                    units_micros=holding.units_micros,
                    purchase_price_minor=holding.purchase_price_minor,
                    current_price_minor=holding.current_price_minor,
                    current_value_minor=holding.current_value_minor,
                    estimated_gain_minor=holding.estimated_gain_minor,
                    currency=holding.currency,
                    version=holding.version,
                )
                for holding in value.holdings
            ],
        )

    def orders_handler(_arguments: BaseModel, context: ToolCallContext) -> OrdersOutput:
        values = list_orders(context.session, actor_id=context.actor_id)
        return OrdersOutput(
            items=[
                OrderToolItem(
                    id=item.id,
                    order_type=item.order_type,
                    product_id=item.product_id,
                    product_name=item.product_name,
                    amount_minor=item.amount_minor,
                    currency=item.currency,
                    status=item.status,
                    executed_at=item.executed_at.isoformat() if item.executed_at else None,
                    holding_id=item.holding_id,
                )
                for item in values
            ]
        )

    def buy_handler(arguments: BaseModel, context: ToolCallContext) -> InvestmentProposalOutput:
        values = InvestmentPurchaseInput.model_validate(arguments)
        return InvestmentProposalOutput.model_validate(
            propose_purchase(
                context.session,
                context=context,
                product_name=values.product_name,
                amount_minor=values.amount_minor,
                account_label=values.account_label,
            )
        )

    def redeem_handler(arguments: BaseModel, context: ToolCallContext) -> InvestmentProposalOutput:
        values = InvestmentRedemptionInput.model_validate(arguments)
        return InvestmentProposalOutput.model_validate(
            propose_redemption(
                context.session,
                context=context,
                product_name=values.product_name,
                amount_minor=values.amount_minor,
                holding_id=values.holding_id,
            )
        )

    return (
        ToolSpec(
            "investment.products",
            "List synthetic products and check them against the server-held risk profile.",
            "1.0",
            ProductQueryInput,
            ProductsOutput,
            "read_only",
            "low",
            "never",
            get_products,
        ),
        ToolSpec(
            "investment.compare",
            "Compare risk, minimum, price, and illustrative yield for synthetic products. "
            "Do not describe estimates as guaranteed.",
            "1.0",
            InvestmentCompareInput,
            ProductsOutput,
            "read_only",
            "low",
            "never",
            compare_products,
        ),
        ToolSpec(
            "investment.profile",
            "Read the current server-held demo risk profile.",
            "1.0",
            InvestmentEmptyInput,
            InvestmentRiskProfileOutput,
            "read_only",
            "low",
            "never",
            profile_handler,
        ),
        ToolSpec(
            "investment.portfolio",
            "Read simulated investment holdings, market value, cash, and total assets.",
            "1.0",
            InvestmentEmptyInput,
            PortfolioOutput,
            "read_only",
            "low",
            "never",
            portfolio_handler,
        ),
        ToolSpec(
            "investment.orders",
            "Read the current user's simulated investment order history.",
            "1.0",
            InvestmentEmptyInput,
            OrdersOutput,
            "read_only",
            "low",
            "never",
            orders_handler,
        ),
        ToolSpec(
            "investment.buy",
            "Propose a simulated purchase only when the user names a product and purchase amount. "
            "The server checks risk suitability and balance. Always require confirmation.",
            "1.0",
            InvestmentPurchaseInput,
            InvestmentProposalOutput,
            "funds_write",
            "high",
            "always",
            buy_handler,
        ),
        ToolSpec(
            "investment.redeem",
            "Propose redemption from an owned synthetic holding. Always require confirmation.",
            "1.0",
            InvestmentRedemptionInput,
            InvestmentProposalOutput,
            "funds_write",
            "high",
            "always",
            redeem_handler,
        ),
    )
