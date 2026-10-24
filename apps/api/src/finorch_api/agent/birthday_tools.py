"""Typed birthday budget and due-reminder tools; no automatic purchase."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finorch_api.agent.context import ToolCallContext
from finorch_api.agent.intent import birthday_plan_intent
from finorch_api.agent.runtime import ToolSpec
from finorch_api.application.birthday_plans import list_birthday_plans, propose_birthday_plan
from finorch_api.application.errors import BankingRuleError


class BirthdayPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    birthday_on: date
    budget_minor: int = Field(gt=0, le=10_000_000, strict=True)
    account_label: str | None = Field(default=None, min_length=1, max_length=80)


class BirthdayPlanProposalOutput(BaseModel):
    status: Literal["awaiting_confirmation"]
    confirmation_required: Literal[True]
    challenge_id: UUID
    plan_id: UUID
    account_label: str
    birthday_on: date
    purchase_on: date
    budget_minor: int
    catalog_total_minor: int
    currency: Literal["CNY"]
    items: list[Literal["flowers", "cake"]]
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


class BirthdayPlanItem(BaseModel):
    id: UUID
    account_id: UUID
    account_label: str
    birthday_on: date
    purchase_on: date
    budget_minor: int
    catalog_total_minor: int
    currency: Literal["CNY"]
    status: Literal["scheduled"]
    due_for_reconfirmation: bool
    funds_held: Literal[False]
    order_placed: Literal[False]
    items: list[dict[str, str | int]]
    next_action: str


class BirthdayPlansOutput(BaseModel):
    items: list[BirthdayPlanItem]


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def birthday_tool_specs() -> tuple[ToolSpec, ...]:
    def propose(arguments: BaseModel, context: ToolCallContext) -> BirthdayPlanProposalOutput:
        typed = BirthdayPlanInput.model_validate(arguments)
        intent = birthday_plan_intent(context.task.request_text)
        if (
            intent is None
            or typed.birthday_on != intent.birthday_on
            or typed.budget_minor != intent.budget_minor
            or typed.account_label != intent.account_label
        ):
            raise BankingRuleError(
                "birthday_parameter_mismatch", "生日日期、预算或账户与用户请求不一致。"
            )
        return BirthdayPlanProposalOutput.model_validate(
            propose_birthday_plan(
                context.session,
                context=context,
                birthday_on=typed.birthday_on,
                budget_minor=typed.budget_minor,
                account_label=typed.account_label,
            )
        )

    def list_plans(_arguments: BaseModel, context: ToolCallContext) -> BirthdayPlansOutput:
        return BirthdayPlansOutput.model_validate(
            {"items": list_birthday_plans(context.session, actor_id=context.actor_id)}
        )

    return (
        ToolSpec(
            name="birthday.list",
            version="1.0",
            description=(
                "Read the user's confirmed synthetic birthday budget intentions "
                "and due reminders. Funds are not held and no order is placed."
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
                "Propose a synthetic birthday budget and a reminder two days before "
                "the supplied birthday. Requires server confirmation. Never holds funds "
                "or places an order; purchases require new confirmation when due."
            ),
            input_model=BirthdayPlanInput,
            output_model=BirthdayPlanProposalOutput,
            permission_level="reversible_write",
            risk_level="medium",
            confirmation_requirement="always",
            handler=propose,
        ),
    )
