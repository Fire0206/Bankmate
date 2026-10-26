"""Typed birthday budget, reservation, reminder and confirmed order tools."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from finorch_api.agent.context import ToolCallContext
from finorch_api.agent.intent import birthday_plan_intent
from finorch_api.agent.runtime import ToolSpec
from finorch_api.application.birthday_plans import (
    list_birthday_plans,
    propose_birthday_order,
    propose_birthday_plan,
    propose_birthday_plan_change,
)
from finorch_api.application.errors import BankingRuleError
from finorch_api.infrastructure.models import ToolExecution


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BirthdayProduct(BaseModel):
    product_code: Literal["flowers", "cake"]
    product_name: str
    unit_price_minor: int
    quantity: int


class BirthdayPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    birthday_on: date
    budget_minor: int = Field(gt=0, le=10_000_000, strict=True)
    account_label: str | None = Field(default=None, min_length=1, max_length=80)
    card_suffix: str | None = Field(default=None, pattern=r"^\d{4}$")


class BirthdayPlanProposalOutput(BaseModel):
    status: Literal["awaiting_confirmation"]
    confirmation_required: Literal[True]
    challenge_id: UUID
    plan_id: UUID
    account_label: str
    card_suffix: str
    birthday_on: date
    purchase_on: date
    budget_minor: int
    catalog_total_minor: int
    currency: Literal["CNY"]
    items: list[BirthdayProduct]
    merchant: str
    pickup_location: str
    funds_held: Literal[False]
    order_placed: Literal[False]
    current_status: Literal["pending_confirmation"]
    target_status: Literal["scheduled"]
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
    resource_type: Literal["birthday_plan"]
    resource_id: UUID
    resource_label: str
    resource_version: int


class BirthdayPlanOrder(BaseModel):
    id: UUID
    merchant: str
    items: list[BirthdayProduct]
    total_amount_minor: int
    currency: Literal["CNY"]
    pickup_location: str
    scheduled_for: date
    status: str
    transaction_id: UUID | None
    paid_at: datetime | None


class BirthdayPlanItem(BaseModel):
    id: UUID
    account_id: UUID
    account_label: str
    card_suffix: str | None
    birthday_on: date
    purchase_on: date
    budget_minor: int
    catalog_total_minor: int
    currency: Literal["CNY"]
    status: Literal["pending_confirmation", "scheduled", "cancelled", "completed"]
    due_for_confirmation: bool
    due_for_reconfirmation: bool
    funds_held: bool
    held_minor: int
    order_status: str | None
    order_placed: bool
    items: list[BirthdayProduct]
    order: BirthdayPlanOrder | None
    next_action: str


class BirthdayPlansOutput(BaseModel):
    items: list[BirthdayPlanItem]


class BirthdayOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID


class BirthdayOrderProposalOutput(BaseModel):
    status: Literal["awaiting_confirmation"]
    confirmation_required: Literal[True]
    challenge_id: UUID
    plan_id: UUID
    order_id: UUID
    account_label: str
    card_suffix: str
    birthday_on: date
    scheduled_for: date
    items: list[BirthdayProduct]
    amount_minor: int
    currency: Literal["CNY"]
    merchant: str
    pickup_location: str
    held_minor: int
    current_status: Literal["awaiting_confirmation"]
    target_status: Literal["paid"]
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
    resource_type: Literal["birthday_order"]
    resource_id: UUID
    resource_label: str
    resource_version: int


class BirthdayPlanChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    budget_minor: int | None = Field(default=None, gt=0, le=10_000_000, strict=True)


class BirthdayPlanChangeProposalOutput(BaseModel):
    status: Literal["awaiting_confirmation"]
    confirmation_required: Literal[True]
    challenge_id: UUID
    plan_id: UUID
    account_label: str
    birthday_on: date
    purchase_on: date
    current_budget_minor: int
    budget_minor: int | None
    current_status: Literal["scheduled"]
    target_status: Literal["updated", "cancelled"]
    funds_held: bool
    order_placed: Literal[False]
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
    resource_type: Literal["birthday_plan"]
    resource_id: UUID
    resource_label: str
    resource_version: int


def birthday_tool_specs() -> tuple[ToolSpec, ...]:
    def propose(arguments: BaseModel, context: ToolCallContext) -> BirthdayPlanProposalOutput:
        BirthdayPlanInput.model_validate(arguments)
        intent = birthday_plan_intent(context.task.request_text)
        if intent is None or intent.birthday_on is None or intent.budget_minor is None:
            raise BankingRuleError(
                "birthday_parameter_mismatch", "生日计划缺少用户明确提供的日期或预算。"
            )
        return BirthdayPlanProposalOutput.model_validate(
            propose_birthday_plan(
                context.session,
                context=context,
                # The original request is the source of truth for date, budget, account and
                # card. Never let an LLM-generated value replace an explicit financial choice.
                birthday_on=intent.birthday_on,
                budget_minor=intent.budget_minor,
                account_label=intent.account_label,
                card_suffix=intent.card_suffix,
            )
        )

    def list_plans(_arguments: BaseModel, context: ToolCallContext) -> BirthdayPlansOutput:
        return BirthdayPlansOutput.model_validate(
            {"items": list_birthday_plans(context.session, actor_id=context.actor_id)}
        )

    def propose_order(
        arguments: BaseModel, context: ToolCallContext
    ) -> BirthdayOrderProposalOutput:
        typed = BirthdayOrderInput.model_validate(arguments)
        prior_items = _previous_plans(context)
        if not any(str(item.get("id")) == str(typed.plan_id) for item in prior_items):
            raise BankingRuleError(
                "birthday_plan_not_found", "请先读取当前用户的生日计划，再选择其中一项。"
            )
        if not any(
            word in context.task.request_text for word in ("确认购买", "现在订", "下单", "购买")
        ):
            raise BankingRuleError(
                "birthday_purchase_intent_required", "请明确表示确认购买后再继续。"
            )
        return BirthdayOrderProposalOutput.model_validate(
            propose_birthday_order(context.session, context=context, plan_id=typed.plan_id)
        )

    def propose_budget_update(
        arguments: BaseModel, context: ToolCallContext
    ) -> BirthdayPlanChangeProposalOutput:
        typed = BirthdayPlanChangeInput.model_validate(arguments)
        _require_previous_plan(context, typed.plan_id)
        return BirthdayPlanChangeProposalOutput.model_validate(
            propose_birthday_plan_change(
                context.session,
                context=context,
                plan_id=typed.plan_id,
                target_status="updated",
                budget_minor=typed.budget_minor,
            )
        )

    def propose_cancel(
        arguments: BaseModel, context: ToolCallContext
    ) -> BirthdayPlanChangeProposalOutput:
        typed = BirthdayPlanChangeInput.model_validate(arguments)
        _require_previous_plan(context, typed.plan_id)
        return BirthdayPlanChangeProposalOutput.model_validate(
            propose_birthday_plan_change(
                context.session,
                context=context,
                plan_id=typed.plan_id,
                target_status="cancelled",
            )
        )

    return (
        ToolSpec(
            name="birthday.list",
            version="1.0",
            description=(
                "Read the current user's synthetic birthday budgets, held amounts, scheduled or "
                "due gift orders, and paid results. This read never authorizes a purchase."
            ),
            input_model=EmptyInput,
            output_model=BirthdayPlansOutput,
            permission_level="read_only",
            risk_level="low",
            confirmation_requirement="never",
            handler=list_plans,
        ),
        ToolSpec(
            name="birthday.plan",
            version="1.0",
            description=(
                "Create a synthetic birthday gift plan for flowers and cake. Confirmation holds "
                "the stated budget without debiting the account. A due order always needs a new "
                "explicit purchase request and confirmation."
            ),
            input_model=BirthdayPlanInput,
            output_model=BirthdayPlanProposalOutput,
            permission_level="reversible_write",
            risk_level="medium",
            confirmation_requirement="always",
            handler=propose,
        ),
        ToolSpec(
            name="birthday.order",
            version="1.0",
            description=(
                "Propose purchase of an already-due synthetic birthday order after the user "
                "explicitly says to confirm or place the order. Never auto-pays."
            ),
            input_model=BirthdayOrderInput,
            output_model=BirthdayOrderProposalOutput,
            permission_level="financial_write",
            risk_level="high",
            confirmation_requirement="always",
            handler=propose_order,
        ),
        ToolSpec(
            name="birthday.budget_update",
            version="1.0",
            description=(
                "Propose a new bounded budget for an existing scheduled birthday plan. "
                "Requires a fresh confirmation and releases or reserves only the difference."
            ),
            input_model=BirthdayPlanChangeInput,
            output_model=BirthdayPlanChangeProposalOutput,
            permission_level="financial_write",
            risk_level="high",
            confirmation_requirement="always",
            handler=propose_budget_update,
        ),
        ToolSpec(
            name="birthday.cancel",
            version="1.0",
            description=(
                "Propose cancellation of a scheduled birthday plan. Confirmation releases all "
                "remaining held funds and cancels any unpaid simulated order."
            ),
            input_model=BirthdayPlanChangeInput,
            output_model=BirthdayPlanChangeProposalOutput,
            permission_level="reversible_write",
            risk_level="medium",
            confirmation_requirement="always",
            handler=propose_cancel,
        ),
    )


def _previous_plans(context: ToolCallContext) -> list[dict[str, Any]]:
    execution = context.session.scalar(
        select(ToolExecution)
        .where(
            ToolExecution.task_id == context.task.id,
            ToolExecution.tool_name == "birthday.list",
            ToolExecution.status == "succeeded",
        )
        .order_by(ToolExecution.completed_at.desc())
        .limit(1)
    )
    if execution is None or not isinstance(execution.result_data, dict):
        return []
    rows = execution.result_data.get("items", [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _require_previous_plan(context: ToolCallContext, plan_id: UUID) -> None:
    if not any(str(item.get("id")) == str(plan_id) for item in _previous_plans(context)):
        raise BankingRuleError(
            "birthday_plan_not_found", "请先读取当前用户的生日计划，再选择其中一项。"
        )
