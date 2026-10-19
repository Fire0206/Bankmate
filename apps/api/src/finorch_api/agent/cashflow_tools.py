from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from finorch_api.agent.context import ToolCallContext
from finorch_api.agent.runtime import ToolSpec
from finorch_api.application.cashflow import plan_payday_allocation


class PaydayPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_name: str = Field(min_length=1, max_length=80)
    transfer_amount_minor: int = Field(
        gt=0,
        le=10_000_000_000,
        description="CNY integer fen; 200 yuan = 20000 fen.",
    )
    reserve_amount_minor: int = Field(
        ge=0,
        le=10_000_000_000,
        description="CNY integer fen the user wants to keep after transfer and investment.",
    )
    source_account_label: str | None = Field(default=None, max_length=80)
    month: str | None = Field(default=None, pattern=r"^20\d{2}-(0[1-9]|1[0-2])$")


class PaydayPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_label: str
    currency: str
    month: str
    account_balance_minor: int
    monthly_income_minor: int
    monthly_expense_minor: int
    recipient_name: str
    transfer_amount_minor: int
    reserve_amount_minor: int
    remaining_after_transfer_minor: int
    investment_budget_minor: int
    reserve_shortfall_minor: int


def cashflow_tool_specs() -> tuple[ToolSpec, ...]:
    def handler(arguments: BaseModel, context: ToolCallContext) -> dict[str, Any]:
        values = PaydayPlanInput.model_validate(arguments)
        return PaydayPlanOutput.model_validate(
            plan_payday_allocation(
                context.session,
                actor_id=context.actor_id,
                recipient_name=values.recipient_name,
                transfer_amount_minor=values.transfer_amount_minor,
                reserve_amount_minor=values.reserve_amount_minor,
                source_account_label=values.source_account_label,
                month=values.month,
            ).__dict__
        )

    return (
        ToolSpec(
            name="finance.payday_plan",
            description=(
                "Calculate a server-side payday allocation from an owned account balance, "
                "real synthetic monthly income/expense totals, a named recipient, a specified "
                "transfer, and the user's reserve. Use the returned investment_budget_minor "
                "as the maximum later investment amount; do not calculate or exceed it. "
                "This tool only plans and never changes balances."
            ),
            version="1.0",
            input_model=PaydayPlanInput,
            output_model=PaydayPlanOutput,
            permission_level="read_only",
            risk_level="low",
            confirmation_requirement="never",
            handler=handler,
        ),
    )
