from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.orm import Session

from finorch_api.agent.cashflow_tools import cashflow_tool_specs
from finorch_api.agent.context import ToolCallContext
from finorch_api.agent.investment_tools import investment_tool_specs
from finorch_api.agent.runtime import ToolRegistry, ToolSpec
from finorch_api.agent.tools import (
    BillAnnualInput,
    BillAnnualOutput,
    BillAnomaliesOutput,
    BillMonthInput,
    BillSummaryInput,
    BillSummaryOutput,
    BillTransactionsInput,
    BillTransactionsOutput,
    CardChangeProposalOutput,
    CardGetOutput,
    CardListOutput,
    CardSuffixInput,
    CardToolItem,
    EmptyToolInput,
    SubscriptionChangeProposalOutput,
    SubscriptionListOutput,
    SubscriptionNameInput,
    SubscriptionRemindersOutput,
    SubscriptionToolItem,
)
from finorch_api.agent.transfer_tools import transfer_tool_specs
from finorch_api.application.bills import (
    get_annual_report,
    get_month_anomalies,
    get_monthly_summary,
    list_transactions,
)
from finorch_api.application.cards import CardNotFoundError, CardView, list_cards
from finorch_api.application.confirmation import parameters_hash as hash_parameters
from finorch_api.application.subscriptions import (
    find_owned_subscription,
    list_subscription_reminders,
    list_subscriptions,
)
from finorch_api.domain.cards import CardStatus, transition_card_status
from finorch_api.domain.subscriptions import transition_subscription_status
from finorch_api.infrastructure.models import ConfirmationChallenge, utc_now

POLICY_VERSION = "card-confirmation-v1"
SUBSCRIPTION_POLICY_VERSION = "subscription-confirmation-v1"
TOOL_VERSION = "1.0"
CONFIRMATION_TTL = timedelta(minutes=5)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def card_result_payload(card: CardView) -> dict[str, Any]:
    return {
        "id": str(card.id),
        "account_id": str(card.account_id),
        "label": card.label,
        "card_suffix": card.card_suffix,
        "status": card.status.value,
        "version": card.version,
    }


def _card_for_suffix(session: Session, *, actor_id: UUID, suffix: str) -> CardView:
    page = list_cards(session, actor_id=actor_id, limit=100)
    matches = [card for card in page.items if card.card_suffix == suffix]
    if not matches:
        raise CardNotFoundError
    if len(matches) > 1:
        raise ToolTargetAmbiguousError
    return matches[0]


class ToolTargetAmbiguousError(RuntimeError):
    """More than one owned card matched a requested suffix."""


def _card_change_proposal(
    *,
    context: ToolCallContext,
    card_suffix: str,
    target_status: CardStatus,
) -> CardChangeProposalOutput:
    card_view = _card_for_suffix(context.session, actor_id=context.actor_id, suffix=card_suffix)
    transition_card_status(card_view.status, target_status)
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "card_id": str(card_view.id),
        "target_status": target_status.value,
    }
    parameters_hash = hash_parameters(normalized)
    context.execution.input_hash = parameters_hash
    challenge = ConfirmationChallenge(
        id=uuid4(),
        task_id=context.task.id,
        tool_execution_id=context.execution.id,
        actor_id=context.actor_id,
        card_id=card_view.id,
        tool_name=context.execution.tool_name,
        tool_version=context.execution.tool_version,
        target_status=target_status.value,
        parameters_hash=parameters_hash,
        card_version=card_view.version,
        policy_version=POLICY_VERSION,
        idempotency_key=context.execution.idempotency_key,
        status="pending",
        expires_at=utc_now() + CONFIRMATION_TTL,
    )
    context.session.add(challenge)
    context.session.flush()
    return CardChangeProposalOutput(
        status="awaiting_confirmation",
        confirmation_required=True,
        challenge_id=challenge.id,
        card_id=card_view.id,
        card_suffix=card_view.card_suffix,
        card_label=card_view.label,
        current_status=card_view.status.value,
        target_status=target_status.value,
        card_version=card_view.version,
        parameters_hash=parameters_hash,
        idempotency_key=challenge.idempotency_key,
        expires_at=_utc(challenge.expires_at),
        resource_type="card",
        resource_id=card_view.id,
        resource_label=card_view.label,
        resource_version=card_view.version,
    )


def _subscription_change_proposal(
    *,
    context: ToolCallContext,
    merchant_name: str,
    target_status: str,
) -> SubscriptionChangeProposalOutput:
    subscription = find_owned_subscription(
        context.session, actor_id=context.actor_id, merchant_name=merchant_name
    )
    transition_subscription_status(subscription.status, target_status)
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "subscription_id": str(subscription.id),
        "target_status": target_status,
    }
    parameters_hash = hash_parameters(normalized)
    context.execution.input_hash = parameters_hash
    challenge = ConfirmationChallenge(
        id=uuid4(),
        task_id=context.task.id,
        tool_execution_id=context.execution.id,
        actor_id=context.actor_id,
        card_id=None,
        subscription_id=subscription.id,
        tool_name=context.execution.tool_name,
        tool_version=context.execution.tool_version,
        target_status=target_status,
        parameters_hash=parameters_hash,
        card_version=None,
        subscription_version=subscription.version,
        policy_version=SUBSCRIPTION_POLICY_VERSION,
        idempotency_key=context.execution.idempotency_key,
        status="pending",
        expires_at=utc_now() + CONFIRMATION_TTL,
    )
    context.session.add(challenge)
    context.session.flush()
    return SubscriptionChangeProposalOutput(
        status="awaiting_confirmation",
        confirmation_required=True,
        challenge_id=challenge.id,
        subscription_id=subscription.id,
        merchant=subscription.merchant,
        current_status=subscription.status,
        target_status=target_status,
        subscription_version=subscription.version,
        parameters_hash=parameters_hash,
        idempotency_key=challenge.idempotency_key,
        expires_at=_utc(challenge.expires_at),
        resource_type="subscription",
        resource_id=subscription.id,
        resource_label=subscription.merchant,
        resource_version=subscription.version,
    )


def _bill_transaction_output(value: Any) -> dict[str, Any]:
    return {
        "id": value.id,
        "direction": value.direction,
        "amount_minor": value.amount_minor,
        "currency": value.currency,
        "merchant": value.merchant,
        "category": value.category,
        "occurred_at": value.occurred_at,
        "anomaly_reason": value.anomaly_reason,
        "source_card_suffix": value.source_card_suffix,
    }


def build_tool_registry() -> ToolRegistry:
    def list_handler(_arguments: BaseModel, context: ToolCallContext) -> CardListOutput:
        page = list_cards(context.session, actor_id=context.actor_id, limit=100)
        return CardListOutput(
            items=[CardToolItem.model_validate(card_result_payload(card)) for card in page.items],
            next_cursor=None,
        )

    def get_handler(arguments: BaseModel, context: ToolCallContext) -> CardGetOutput:
        typed = CardSuffixInput.model_validate(arguments)
        card = _card_for_suffix(
            context.session, actor_id=context.actor_id, suffix=typed.card_suffix
        )
        return CardGetOutput.model_validate(card_result_payload(card))

    def freeze_handler(arguments: BaseModel, context: ToolCallContext) -> CardChangeProposalOutput:
        typed = CardSuffixInput.model_validate(arguments)
        return _card_change_proposal(
            context=context, card_suffix=typed.card_suffix, target_status=CardStatus.FROZEN
        )

    def unfreeze_handler(
        arguments: BaseModel, context: ToolCallContext
    ) -> CardChangeProposalOutput:
        typed = CardSuffixInput.model_validate(arguments)
        return _card_change_proposal(
            context=context, card_suffix=typed.card_suffix, target_status=CardStatus.ACTIVE
        )

    def report_lost_handler(
        arguments: BaseModel, context: ToolCallContext
    ) -> CardChangeProposalOutput:
        typed = CardSuffixInput.model_validate(arguments)
        return _card_change_proposal(
            context=context, card_suffix=typed.card_suffix, target_status=CardStatus.LOST
        )

    def bill_summary_handler(arguments: BaseModel, context: ToolCallContext) -> BillSummaryOutput:
        typed = BillSummaryInput.model_validate(arguments)
        view = get_monthly_summary(
            context.session,
            actor_id=context.actor_id,
            month=typed.month,
            category=typed.category,
        )
        data = asdict(view)
        data["anomalies"] = [_bill_transaction_output(item) for item in view.anomalies]
        return BillSummaryOutput.model_validate(data)

    def bill_annual_handler(arguments: BaseModel, context: ToolCallContext) -> BillAnnualOutput:
        typed = BillAnnualInput.model_validate(arguments)
        view = get_annual_report(context.session, actor_id=context.actor_id, year=typed.year)
        data = asdict(view)
        data["anomalies"] = [_bill_transaction_output(item) for item in view.anomalies]
        return BillAnnualOutput.model_validate(data)

    def bill_transactions_handler(
        arguments: BaseModel, context: ToolCallContext
    ) -> BillTransactionsOutput:
        typed = BillTransactionsInput.model_validate(arguments)
        page = list_transactions(
            context.session,
            actor_id=context.actor_id,
            month=typed.month,
            category=typed.category,
            merchant=typed.merchant,
            limit=100,
        )
        month = typed.month or datetime.now(UTC).strftime("%Y-%m")
        return BillTransactionsOutput(
            month=month,
            items=[_bill_transaction_output(item) for item in page.items],
            total=page.total,
        )

    def bill_anomalies_handler(
        arguments: BaseModel, context: ToolCallContext
    ) -> BillAnomaliesOutput:
        typed = BillMonthInput.model_validate(arguments)
        items = get_month_anomalies(context.session, actor_id=context.actor_id, month=typed.month)
        month = typed.month or datetime.now(UTC).strftime("%Y-%m")
        return BillAnomaliesOutput(
            month=month,
            items=[_bill_transaction_output(item) for item in items],
        )

    def subscription_list_handler(
        _arguments: BaseModel, context: ToolCallContext
    ) -> SubscriptionListOutput:
        result = list_subscriptions(context.session, actor_id=context.actor_id)
        items = [
            SubscriptionToolItem(
                id=item.id,
                merchant=item.merchant,
                amount_minor=item.amount_minor,
                currency=item.currency,
                billing_cycle="monthly",
                status=item.status,
                next_charge_at=item.next_charge_at,
                version=item.version,
                detected_charge_count=item.detected_charge_count,
                reminder_days_before=item.reminder_days_before,
                last_reminded_charge_at=item.last_reminded_charge_at,
            )
            for item in result.items
        ]
        return SubscriptionListOutput(
            items=items,
            monthly_total_minor=result.monthly_total_minor,
            currency=result.currency,
        )

    def subscription_reminders_handler(
        _arguments: BaseModel, context: ToolCallContext
    ) -> SubscriptionRemindersOutput:
        items = list_subscription_reminders(context.session, actor_id=context.actor_id)
        return SubscriptionRemindersOutput.model_validate(
            {"items": [asdict(item) for item in items]}
        )

    def subscription_change_handler(target_status: str):
        def handle(arguments: BaseModel, context: ToolCallContext):
            typed = SubscriptionNameInput.model_validate(arguments)
            return _subscription_change_proposal(
                context=context,
                merchant_name=typed.merchant_name,
                target_status=target_status,
            )

        return handle

    subscription_action_guidance = {
        "pause": "Temporarily stop upcoming automatic charges; the subscription remains resumable.",
        "resume": "Re-enable automatic charges for a paused subscription.",
        "cancel": "Permanently stop future renewal; do not use for a temporary pause.",
    }

    return ToolRegistry(
        (
            ToolSpec(
                name="card.list",
                description="List the current authenticated demo user's synthetic cards.",
                version=TOOL_VERSION,
                input_model=EmptyToolInput,
                output_model=CardListOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=list_handler,
            ),
            ToolSpec(
                name="card.get",
                description="Read one of the current demo user's cards by its four-digit suffix.",
                version=TOOL_VERSION,
                input_model=CardSuffixInput,
                output_model=CardGetOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=get_handler,
            ),
            ToolSpec(
                name="card.freeze",
                description=(
                    "Propose freezing an owned synthetic card; "
                    "this always requires user confirmation."
                ),
                version=TOOL_VERSION,
                input_model=CardSuffixInput,
                output_model=CardChangeProposalOutput,
                permission_level="reversible_write",
                risk_level="medium",
                confirmation_requirement="always",
                handler=freeze_handler,
            ),
            ToolSpec(
                name="card.unfreeze",
                description=(
                    "Propose unfreezing an owned synthetic card; "
                    "this always requires user confirmation."
                ),
                version=TOOL_VERSION,
                input_model=CardSuffixInput,
                output_model=CardChangeProposalOutput,
                permission_level="reversible_write",
                risk_level="medium",
                confirmation_requirement="always",
                handler=unfreeze_handler,
            ),
            ToolSpec(
                name="card.report_lost",
                description=(
                    "Propose reporting an owned synthetic card lost. This permanently blocks "
                    "unfreeze for that card and requires explicit confirmation plus local demo OTP."
                ),
                version=TOOL_VERSION,
                input_model=CardSuffixInput,
                output_model=CardChangeProposalOutput,
                permission_level="high_risk_write",
                risk_level="high",
                confirmation_requirement="always",
                handler=report_lost_handler,
            ),
            ToolSpec(
                name="bill.monthly_summary",
                description=(
                    "Calculate monthly income, expenses, category totals, trends, and "
                    "rule-based anomaly notices for the current demo user."
                ),
                version=TOOL_VERSION,
                input_model=BillSummaryInput,
                output_model=BillSummaryOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=bill_summary_handler,
            ),
            ToolSpec(
                name="bill.annual_report",
                description=(
                    "Calculate a full calendar year's synthetic income, expenses, twelve monthly "
                    "totals, category spending and deterministic anomaly notices."
                ),
                version=TOOL_VERSION,
                input_model=BillAnnualInput,
                output_model=BillAnnualOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=bill_annual_handler,
            ),
            ToolSpec(
                name="bill.transactions",
                description=(
                    "Read the current demo user's synthetic transactions filtered by "
                    "month, category, or merchant."
                ),
                version=TOOL_VERSION,
                input_model=BillTransactionsInput,
                output_model=BillTransactionsOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=bill_transactions_handler,
            ),
            ToolSpec(
                name="bill.anomalies",
                description=(
                    "Find monthly synthetic expenses matching the documented deterministic "
                    "notice rule."
                ),
                version=TOOL_VERSION,
                input_model=BillMonthInput,
                output_model=BillAnomaliesOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=bill_anomalies_handler,
            ),
            ToolSpec(
                name="subscription.list",
                description=(
                    "List recurring subscriptions detected from synthetic transaction "
                    "history with their next charge dates."
                ),
                version=TOOL_VERSION,
                input_model=EmptyToolInput,
                output_model=SubscriptionListOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=subscription_list_handler,
            ),
            ToolSpec(
                name="subscription.reminders",
                description=(
                    "Read upcoming in-app synthetic subscription renewal reminders, "
                    "their due dates, lead days and delivery status. Do not claim a "
                    "merchant was notified or charged."
                ),
                version=TOOL_VERSION,
                input_model=EmptyToolInput,
                output_model=SubscriptionRemindersOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=subscription_reminders_handler,
            ),
            *tuple(
                ToolSpec(
                    name=f"subscription.{action}",
                    description=(
                        f"{subscription_action_guidance[action]} "
                        "Use only for the current user's clearly identified subscription. "
                        "Server-side confirmation is required."
                    ),
                    version=TOOL_VERSION,
                    input_model=SubscriptionNameInput,
                    output_model=SubscriptionChangeProposalOutput,
                    permission_level="reversible_write",
                    risk_level="medium",
                    confirmation_requirement="always",
                    handler=subscription_change_handler(target_status),
                )
                for action, target_status in (
                    ("pause", "paused"),
                    ("resume", "active"),
                    ("cancel", "cancelled"),
                )
            ),
            *transfer_tool_specs(),
            *investment_tool_specs(),
            *cashflow_tool_specs(),
        )
    )
