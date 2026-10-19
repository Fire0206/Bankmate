import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from finorch_api.agent.providers import ProviderSelection
from finorch_api.agent.runtime import (
    AgentProviderError,
    AgentRuntime,
    ModelToolCall,
    ToolDispatchResult,
    ToolExecutionError,
    ToolRegistry,
    ToolSpec,
)
from finorch_api.agent.tools import (
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
    SubscriptionToolItem,
)
from finorch_api.application.bills import (
    get_month_anomalies,
    get_monthly_summary,
    list_transactions,
)
from finorch_api.application.cards import (
    CardNotFoundError,
    CardView,
    CardWriteConflictError,
    freeze_card,
    list_cards,
    unfreeze_card,
)
from finorch_api.application.subscriptions import (
    SubscriptionAmbiguousError,
    SubscriptionNotFoundError,
    SubscriptionWriteConflictError,
    change_subscription_status,
    find_owned_subscription,
    get_owned_subscription,
    list_subscriptions,
)
from finorch_api.application.transactions import write_transaction
from finorch_api.domain.cards import CardStatus, InvalidCardTransition, transition_card_status
from finorch_api.domain.subscriptions import (
    InvalidSubscriptionTransition,
    transition_subscription_status,
)
from finorch_api.infrastructure.models import (
    AgentTask,
    AuditEvent,
    ConfirmationChallenge,
    TaskStep,
    ToolExecution,
    utc_now,
)
from finorch_api.infrastructure.persistence.cards import get_owned_card

POLICY_VERSION = "card-confirmation-v1"
SUBSCRIPTION_POLICY_VERSION = "subscription-confirmation-v1"
TOOL_VERSION = "1.0"
CONFIRMATION_TTL = timedelta(minutes=5)

_TASK_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"planning", "cancelled"},
    "planning": {"awaiting_input", "awaiting_confirmation", "running", "failed", "cancelled"},
    "awaiting_input": {"planning", "cancelled"},
    "awaiting_confirmation": {"running", "planning", "cancelled", "failed"},
    "running": {"awaiting_input", "awaiting_confirmation", "completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


class AgentTaskNotFoundError(LookupError):
    """The task is absent or not visible to the current actor."""


class AgentIdempotencyConflictError(RuntimeError):
    """An idempotency key was reused for different input or a different operation."""


class AgentTaskStateConflictError(RuntimeError):
    """The requested action is not valid in the current persisted task state."""


@dataclass(frozen=True)
class TaskStepView:
    id: UUID
    sequence: int
    step_type: str
    status: str
    summary: str
    tool_name: str | None
    error_code: str | None
    result_summary: str | None
    result_data: dict[str, Any] | None


@dataclass(frozen=True)
class ConfirmationView:
    id: UUID
    resource_type: str
    resource_id: UUID
    resource_label: str
    resource_version: int
    current_status: str
    target_status: str
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
    policy_version: str
    tool_name: str
    tool_version: str
    card_id: UUID | None = None
    card_suffix: str | None = None
    card_label: str | None = None
    card_version: int | None = None
    subscription_id: UUID | None = None
    merchant: str | None = None
    subscription_version: int | None = None


@dataclass(frozen=True)
class AgentTaskView:
    id: UUID
    conversation_id: UUID
    request_text: str
    provider_mode: str
    status: str
    message: str
    error_code: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    steps: tuple[TaskStepView, ...]
    confirmation: ConfirmationView | None


@dataclass(frozen=True)
class AuditSummaryView:
    id: UUID
    event_type: str
    resource_type: str
    resource_id: UUID
    tool_execution_id: UUID | None
    outcome: str
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    occurred_at: datetime


@dataclass(frozen=True)
class ToolCallContext:
    session: Session
    actor_id: UUID
    task: AgentTask
    step: TaskStep
    execution: ToolExecution
    request_id: str


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _transition(task: AgentTask, target: str) -> None:
    if target == task.status:
        return
    if target not in _TASK_TRANSITIONS.get(task.status, set()):
        raise AgentTaskStateConflictError(f"Task cannot move from {task.status} to {target}.")
    task.status = target


def _audit(
    session: Session,
    *,
    actor_id: UUID,
    event_type: str,
    resource_type: str,
    resource_id: UUID,
    request_id: str,
    outcome: str,
    task_id: UUID | None = None,
    tool_execution_id: UUID | None = None,
    card_id: UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_id=actor_id,
            card_id=card_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            previous_status=(before_state or {}).get("status"),
            new_status=(after_state or {}).get("status"),
            resource_version=(after_state or {}).get("version"),
            request_id=request_id,
            task_id=task_id,
            tool_execution_id=tool_execution_id,
            outcome=outcome,
            before_state=before_state,
            after_state=after_state,
        )
    )


def _owned_task(session: Session, *, actor_id: UUID, task_id: UUID) -> AgentTask:
    task = session.scalar(
        select(AgentTask).where(AgentTask.id == task_id, AgentTask.actor_id == actor_id)
    )
    if task is None:
        raise AgentTaskNotFoundError
    return task


def _to_card_item(card: CardView) -> dict[str, Any]:
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
    parameters_hash = _hash(normalized)
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
    parameters_hash = _hash(normalized)
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
    }


def _build_registry() -> ToolRegistry:
    def list_handler(_arguments: BaseModel, context: ToolCallContext) -> CardListOutput:
        page = list_cards(context.session, actor_id=context.actor_id, limit=100)
        return CardListOutput(
            items=[CardToolItem.model_validate(_to_card_item(card)) for card in page.items],
            next_cursor=None,
        )

    def get_handler(arguments: BaseModel, context: ToolCallContext) -> CardGetOutput:
        typed = CardSuffixInput.model_validate(arguments)
        card = _card_for_suffix(
            context.session, actor_id=context.actor_id, suffix=typed.card_suffix
        )
        return CardGetOutput.model_validate(_to_card_item(card))

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
            )
            for item in result.items
        ]
        return SubscriptionListOutput(
            items=items,
            monthly_total_minor=result.monthly_total_minor,
            currency=result.currency,
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
            *tuple(
                ToolSpec(
                    name=f"subscription.{action}",
                    description=(
                        f"Propose a {action} operation for an owned synthetic recurring "
                        "subscription; server-side confirmation is required."
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
        )
    )


def _next_sequence(session: Session, task_id: UUID) -> int:
    current = session.scalar(select(func.max(TaskStep.sequence)).where(TaskStep.task_id == task_id))
    return (current or 0) + 1


def _safe_tool_error(exception: Exception) -> tuple[str, str]:
    if isinstance(exception, CardNotFoundError):
        return "card_not_found", "我没有找到当前模拟用户拥有的这张卡。"
    if isinstance(exception, InvalidCardTransition):
        return "invalid_card_transition", "这张卡已经处于目标状态，未执行变更。"
    if isinstance(exception, ToolTargetAmbiguousError):
        return "ambiguous_card_target", "多张卡匹配该尾号，请提供更明确的卡片信息。"
    if isinstance(exception, SubscriptionNotFoundError):
        return "subscription_not_found", "没有找到当前模拟用户拥有的这项订阅。"
    if isinstance(exception, SubscriptionAmbiguousError):
        return "ambiguous_subscription_target", "订阅名称匹配多项，请提供更完整的名称。"
    if isinstance(exception, InvalidSubscriptionTransition):
        return "invalid_subscription_transition", "这项订阅当前无法变更到请求的状态。"
    if isinstance(exception, SubscriptionWriteConflictError):
        return "subscription_version_conflict", "订阅状态已更新，请重新读取后再操作。"
    if isinstance(exception, ToolExecutionError):
        return exception.code, str(exception)
    if isinstance(exception, ValidationError):
        return "tool_output_invalid", "工具输出未通过服务端 Schema 校验。"
    return "tool_execution_failed", "模拟银行工具执行失败，业务状态未变更。"


def _record_tool_failure(
    session: Session,
    *,
    task: AgentTask,
    step: TaskStep,
    execution: ToolExecution,
    actor_id: UUID,
    request_id: str,
    error: Exception,
) -> ToolDispatchResult:
    code, message = _safe_tool_error(error)
    step.status = "failed"
    step.summary = message
    step.error_code = code
    step.completed_at = utc_now()
    execution.status = "failed"
    execution.error_code = code
    execution.result_summary = message
    execution.result_data = {"status": "failed", "error_code": code}
    execution.completed_at = utc_now()
    before = task.status
    if task.status not in {"failed", "cancelled", "completed"}:
        _transition(task, "failed")
    task.error_code = code
    task.message = message
    _audit(
        session,
        actor_id=actor_id,
        event_type="agent.tool_execution_failed",
        resource_type="task",
        resource_id=task.id,
        request_id=request_id,
        task_id=task.id,
        tool_execution_id=execution.id,
        outcome="failed",
        before_state={"status": before},
        after_state={"status": task.status, "error_code": code},
    )
    return ToolDispatchResult("failed", execution.result_data, message, code)


def _dispatch_tool(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    request_id: str,
    spec: ToolSpec | None,
    parsed: BaseModel | None,
    call: ModelToolCall,
    step_number: int,
    validation_error: Exception | None,
) -> ToolDispatchResult:
    with write_transaction(session, immediate=True):
        task = _owned_task(session, actor_id=actor_id, task_id=task_id)
        if task.status in {"cancelled", "completed", "failed"}:
            return ToolDispatchResult(
                "failed",
                {"status": "cancelled", "error_code": "task_not_running"},
                "任务已结束，没有执行新的工具调用。",
                "task_not_running",
            )

        sequence = _next_sequence(session, task.id)
        tool_name = call.name[:80]
        raw_args = call.arguments[:2000]
        normalized_input = parsed.model_dump(mode="json") if parsed is not None else raw_args
        input_hash = _hash(normalized_input)
        idempotency_key = f"tool:{task.id}:{sequence}"
        step = TaskStep(
            task_id=task.id,
            sequence=sequence,
            step_type="tool",
            status="running",
            summary=f"Validating and running {tool_name}.",
            tool_name=tool_name,
        )
        session.add(step)
        session.flush()
        execution = ToolExecution(
            task_id=task.id,
            step_id=step.id,
            actor_id=actor_id,
            tool_name=tool_name,
            tool_version=spec.version if spec is not None else TOOL_VERSION,
            idempotency_key=idempotency_key,
            input_hash=input_hash,
            status="running",
        )
        session.add(execution)
        session.flush()

        error = validation_error
        if error is None and (spec is None or parsed is None):
            error = ToolExecutionError("unknown_tool", "The requested tool is not registered.")
        if error is not None:
            return _record_tool_failure(
                session,
                task=task,
                step=step,
                execution=execution,
                actor_id=actor_id,
                request_id=request_id,
                error=error,
            )

        context = ToolCallContext(session, actor_id, task, step, execution, request_id)
        try:
            result = spec.output_model.model_validate(spec.handler(parsed, context))
        except (
            CardNotFoundError,
            CardWriteConflictError,
            InvalidCardTransition,
            ToolTargetAmbiguousError,
            SubscriptionNotFoundError,
            SubscriptionAmbiguousError,
            SubscriptionWriteConflictError,
            InvalidSubscriptionTransition,
            ValidationError,
            ToolExecutionError,
        ) as exc:
            return _record_tool_failure(
                session,
                task=task,
                step=step,
                execution=execution,
                actor_id=actor_id,
                request_id=request_id,
                error=exc,
            )

        result_data = result.model_dump(mode="json")
        execution.result_data = result_data
        execution.result_summary = (
            f"{result_data.get('resource_type', 'business')} operation awaits confirmation."
            if result_data.get("status") == "awaiting_confirmation"
            else f"{spec.name} returned a validated result."
        )
        execution.completed_at = utc_now()
        before = task.status
        if result_data.get("status") == "awaiting_confirmation":
            execution.status = "awaiting_confirmation"
            step.status = "awaiting_confirmation"
            step.summary = "已创建服务端确认请求；业务状态尚未变更。"
            _transition(task, "awaiting_confirmation")
            resource_type = str(result_data["resource_type"])
            resource_id = UUID(str(result_data["resource_id"]))
            card_id = resource_id if resource_type == "card" else None
            _audit(
                session,
                actor_id=actor_id,
                event_type=f"{resource_type}.confirmation_requested",
                resource_type=resource_type,
                resource_id=resource_id,
                card_id=card_id,
                request_id=request_id,
                task_id=task.id,
                tool_execution_id=execution.id,
                outcome="awaiting_confirmation",
                before_state={
                    "status": result_data["current_status"],
                    "version": result_data["resource_version"],
                },
                after_state={"status": result_data["target_status"], "confirmation": "pending"},
            )
            target_status = str(result_data["target_status"])
            action = {
                "frozen": "冻结",
                "active": "解冻" if resource_type == "card" else "恢复",
                "paused": "暂停",
                "cancelled": "取消",
            }.get(target_status, "变更")
            label = str(result_data.get("resource_label", "")).strip()
            target = (
                f"尾号 {result_data['card_suffix']} 的银行卡"
                if resource_type == "card"
                else f"{label} 自动续费"
            )
            return ToolDispatchResult(
                "awaiting_confirmation",
                result_data,
                f"已准备好{action}{target}，请先确认。",
            )

        execution.status = "succeeded"
        step.status = "succeeded"
        step.summary = execution.result_summary or "Tool completed."
        step.completed_at = utc_now()
        if task.status == "planning":
            _transition(task, "running")
        _audit(
            session,
            actor_id=actor_id,
            event_type="agent.tool_execution_succeeded",
            resource_type="task",
            resource_id=task.id,
            request_id=request_id,
            task_id=task.id,
            tool_execution_id=execution.id,
            outcome="succeeded",
            before_state={"status": before},
            after_state={"status": task.status, "tool_name": spec.name},
        )
        return ToolDispatchResult("succeeded", result_data)


def _next_recent_card_context(
    session: Session, *, actor_id: UUID, conversation_id: UUID
) -> dict[str, Any]:
    rows = session.scalars(
        select(ToolExecution)
        .join(AgentTask, AgentTask.id == ToolExecution.task_id)
        .where(
            AgentTask.actor_id == actor_id,
            AgentTask.conversation_id == conversation_id,
            ToolExecution.tool_name == "card.freeze",
            ToolExecution.status.in_(("awaiting_confirmation", "succeeded")),
        )
        .order_by(ToolExecution.created_at.desc())
        .limit(10)
    )
    for execution in rows:
        if execution.result_data and execution.result_data.get("card_suffix"):
            return {"recent_card_suffix": execution.result_data["card_suffix"]}
    return {}


def _task_view(session: Session, *, actor_id: UUID, task_id: UUID) -> AgentTaskView:
    task = _owned_task(session, actor_id=actor_id, task_id=task_id)
    steps = list(
        session.scalars(
            select(TaskStep).where(TaskStep.task_id == task_id).order_by(TaskStep.sequence)
        )
    )
    executions = {
        execution.step_id: execution
        for execution in session.scalars(
            select(ToolExecution).where(ToolExecution.task_id == task_id)
        )
    }
    step_views = tuple(
        TaskStepView(
            id=step.id,
            sequence=step.sequence,
            step_type=step.step_type,
            status=step.status,
            summary=step.summary,
            tool_name=step.tool_name,
            error_code=step.error_code,
            result_summary=(executions[step.id].result_summary if step.id in executions else None),
            result_data=(executions[step.id].result_data if step.id in executions else None),
        )
        for step in steps
    )
    challenge = session.scalar(
        select(ConfirmationChallenge)
        .where(ConfirmationChallenge.task_id == task_id, ConfirmationChallenge.status == "pending")
        .order_by(ConfirmationChallenge.created_at.desc())
    )
    confirmation = None
    if challenge is not None:
        card = (
            get_owned_card(session, actor_id=actor_id, card_id=challenge.card_id)
            if challenge.card_id is not None
            else None
        )
        if card is not None:
            confirmation = ConfirmationView(
                id=challenge.id,
                resource_type="card",
                resource_id=card.id,
                resource_label=card.label,
                resource_version=challenge.card_version or card.version,
                current_status=card.status.value,
                target_status=challenge.target_status,
                parameters_hash=challenge.parameters_hash,
                idempotency_key=challenge.idempotency_key,
                expires_at=_utc(challenge.expires_at),
                policy_version=challenge.policy_version,
                tool_name=challenge.tool_name,
                tool_version=challenge.tool_version,
                card_id=card.id,
                card_suffix=card.card_suffix,
                card_label=card.label,
                card_version=challenge.card_version,
            )
        elif challenge.subscription_id is not None:
            subscription = get_owned_subscription(
                session, actor_id=actor_id, subscription_id=challenge.subscription_id
            )
            if subscription is not None:
                confirmation = ConfirmationView(
                    id=challenge.id,
                    resource_type="subscription",
                    resource_id=subscription.id,
                    resource_label=subscription.merchant,
                    resource_version=challenge.subscription_version or subscription.version,
                    current_status=subscription.status,
                    target_status=challenge.target_status,
                    parameters_hash=challenge.parameters_hash,
                    idempotency_key=challenge.idempotency_key,
                    expires_at=_utc(challenge.expires_at),
                    policy_version=challenge.policy_version,
                    tool_name=challenge.tool_name,
                    tool_version=challenge.tool_version,
                    subscription_id=subscription.id,
                    merchant=subscription.merchant,
                    subscription_version=challenge.subscription_version,
                )
    return AgentTaskView(
        id=task.id,
        conversation_id=task.conversation_id,
        request_text=task.request_text,
        provider_mode=task.provider_mode,
        status=task.status,
        message=task.message,
        error_code=task.error_code,
        version=task.version,
        created_at=_utc(task.created_at),
        updated_at=_utc(task.updated_at),
        steps=step_views,
        confirmation=confirmation,
    )


def _record_initial_task(
    session: Session,
    *,
    actor_id: UUID,
    request_text: str,
    conversation_id: UUID,
    idempotency_key: str,
    request_hash: str,
    provider_mode: str,
    request_id: str,
) -> tuple[UUID, bool]:
    with write_transaction(session, immediate=True):
        existing = session.scalar(
            select(AgentTask).where(
                AgentTask.actor_id == actor_id, AgentTask.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AgentIdempotencyConflictError
            return existing.id, False
        task = AgentTask(
            actor_id=actor_id,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            request_text=request_text,
            provider_mode=provider_mode,
            status="pending",
            message="正在理解你的请求。",
        )
        session.add(task)
        session.flush()
        _transition(task, "planning")
        session.add(
            TaskStep(
                task_id=task.id,
                sequence=1,
                step_type="planner",
                status="running",
                summary=f"Planning with {provider_mode} provider.",
            )
        )
        _audit(
            session,
            actor_id=actor_id,
            event_type="agent.task_created",
            resource_type="task",
            resource_id=task.id,
            request_id=request_id,
            task_id=task.id,
            outcome="succeeded",
            after_state={"status": task.status, "provider_mode": provider_mode},
        )
        session.flush()
        return task.id, True


def _finalize_run(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    request_id: str,
    status: str,
    message: str,
    error_code: str | None,
) -> None:
    with write_transaction(session):
        task = _owned_task(session, actor_id=actor_id, task_id=task_id)
        before = task.status
        if task.status not in {"awaiting_confirmation", "completed", "failed", "cancelled"}:
            target = status
            if target == "completed" and task.status == "planning":
                target = "awaiting_input"
            _transition(task, target)
        task.message = message[:1200]
        task.error_code = error_code
        planner = session.scalar(
            select(TaskStep)
            .where(TaskStep.task_id == task.id, TaskStep.status == "running")
            .order_by(TaskStep.sequence)
        )
        if planner is not None:
            planner.status = "failed" if error_code else "succeeded"
            planner.summary = (
                "Request processing failed." if error_code else "Request planning step completed."
            )
            planner.error_code = error_code
            planner.completed_at = utc_now()
        if before != task.status or error_code:
            _audit(
                session,
                actor_id=actor_id,
                event_type="agent.task_state_changed",
                resource_type="task",
                resource_id=task.id,
                request_id=request_id,
                task_id=task.id,
                outcome="failed" if error_code else "succeeded",
                before_state={"status": before},
                after_state={"status": task.status, "error_code": error_code},
            )


def _run_task(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    request_text: str,
    conversation_id: UUID,
    request_id: str,
    selection: ProviderSelection,
) -> AgentTaskView:
    if selection.error is not None or selection.provider is None:
        error = selection.error or AgentProviderError(
            "provider_not_configured", "The selected provider is not configured."
        )
        message = "模型服务未配置或不可用；没有执行业务变更。"
        _finalize_run(
            session,
            actor_id=actor_id,
            task_id=task_id,
            request_id=request_id,
            status="failed",
            message=message,
            error_code=error.code,
        )
        return _task_view(session, actor_id=actor_id, task_id=task_id)

    trusted_context = _next_recent_card_context(
        session, actor_id=actor_id, conversation_id=conversation_id
    )
    registry = _build_registry()

    def dispatch(
        spec: ToolSpec | None,
        parsed: BaseModel | None,
        call: ModelToolCall,
        step_number: int,
        error: Exception | None,
    ) -> ToolDispatchResult:
        return _dispatch_tool(
            session,
            actor_id=actor_id,
            task_id=task_id,
            request_id=request_id,
            spec=spec,
            parsed=parsed,
            call=call,
            step_number=step_number,
            validation_error=error,
        )

    try:
        result = AgentRuntime(selection.provider, max_steps=4).run(
            request_text=request_text,
            trusted_context=trusted_context,
            registry=registry,
            dispatch=dispatch,
        )
    except AgentProviderError as exc:
        _finalize_run(
            session,
            actor_id=actor_id,
            task_id=task_id,
            request_id=request_id,
            status="failed",
            message="模型服务调用失败；没有基于模型文本执行业务变更。",
            error_code=exc.code,
        )
        return _task_view(session, actor_id=actor_id, task_id=task_id)

    _finalize_run(
        session,
        actor_id=actor_id,
        task_id=task_id,
        request_id=request_id,
        status=result.status,
        message=result.message,
        error_code=result.error_code,
    )
    return _task_view(session, actor_id=actor_id, task_id=task_id)


def create_agent_task(
    session: Session,
    *,
    actor_id: UUID,
    request_text: str,
    conversation_id: UUID,
    idempotency_key: str,
    request_id: str,
    selection: ProviderSelection,
) -> AgentTaskView:
    normalized = {"request_text": request_text, "conversation_id": str(conversation_id)}
    request_hash = _hash(normalized)
    existing = session.scalar(
        select(AgentTask).where(
            AgentTask.actor_id == actor_id, AgentTask.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise AgentIdempotencyConflictError
        return _task_view(session, actor_id=actor_id, task_id=existing.id)

    task_id, created = _record_initial_task(
        session,
        actor_id=actor_id,
        request_text=request_text,
        conversation_id=conversation_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        provider_mode=selection.mode,
        request_id=request_id,
    )
    if not created:
        return _task_view(session, actor_id=actor_id, task_id=task_id)
    return _run_task(
        session,
        actor_id=actor_id,
        task_id=task_id,
        request_text=request_text,
        conversation_id=conversation_id,
        request_id=request_id,
        selection=selection,
    )


def _expire_pending_confirmation(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    request_id: str,
) -> None:
    task = _owned_task(session, actor_id=actor_id, task_id=task_id)
    challenge = session.scalar(
        select(ConfirmationChallenge).where(
            ConfirmationChallenge.task_id == task_id,
            ConfirmationChallenge.actor_id == actor_id,
            ConfirmationChallenge.status == "pending",
        )
    )
    if (
        task.status != "awaiting_confirmation"
        or challenge is None
        or _utc(challenge.expires_at) > utc_now()
    ):
        return

    with write_transaction(session, immediate=True):
        task = _owned_task(session, actor_id=actor_id, task_id=task_id)
        challenge = session.scalar(
            select(ConfirmationChallenge).where(
                ConfirmationChallenge.id == challenge.id,
                ConfirmationChallenge.actor_id == actor_id,
                ConfirmationChallenge.status == "pending",
            )
        )
        if (
            task.status != "awaiting_confirmation"
            or challenge is None
            or _utc(challenge.expires_at) > utc_now()
        ):
            return

        execution = session.get(ToolExecution, challenge.tool_execution_id)
        if execution is None:
            raise AgentTaskNotFoundError
        step = session.get(TaskStep, execution.step_id)
        challenge.status = "expired"
        execution.status = "failed"
        execution.error_code = "confirmation_expired"
        execution.completed_at = utc_now()
        if step is not None:
            step.status = "failed"
            step.error_code = "confirmation_expired"
            step.summary = "The confirmation expired; no business state change was made."
            step.completed_at = utc_now()
        _transition(task, "failed")
        task.error_code = "confirmation_expired"
        resource_type = "card" if challenge.card_id is not None else "subscription"
        resource_id = challenge.card_id or challenge.subscription_id
        task.message = "确认已过期，业务状态没有改变。"
        _audit(
            session,
            actor_id=actor_id,
            event_type=f"{resource_type}.confirmation_expired",
            resource_type=resource_type,
            resource_id=resource_id,
            card_id=challenge.card_id,
            request_id=request_id,
            task_id=task.id,
            tool_execution_id=execution.id,
            outcome="expired",
            before_state={"task_status": "awaiting_confirmation", "confirmation": "pending"},
            after_state={"task_status": "failed", "confirmation": "expired"},
        )


def get_agent_task(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    request_id: str,
) -> AgentTaskView:
    _expire_pending_confirmation(session, actor_id=actor_id, task_id=task_id, request_id=request_id)
    return _task_view(session, actor_id=actor_id, task_id=task_id)


def get_recent_agent_task(
    session: Session,
    *,
    actor_id: UUID,
    conversation_id: UUID,
    request_id: str,
) -> AgentTaskView | None:
    task_id = session.scalar(
        select(AgentTask.id)
        .where(
            AgentTask.actor_id == actor_id,
            AgentTask.conversation_id == conversation_id,
        )
        .order_by(
            case(
                (
                    AgentTask.status.in_(
                        {
                            "pending",
                            "planning",
                            "awaiting_input",
                            "awaiting_confirmation",
                            "running",
                        }
                    ),
                    0,
                ),
                else_=1,
            ),
            AgentTask.created_at.desc(),
            AgentTask.id.desc(),
        )
        .limit(1)
    )
    if task_id is None:
        return None
    return get_agent_task(session, actor_id=actor_id, task_id=task_id, request_id=request_id)


def get_agent_task_by_idempotency_key(
    session: Session,
    *,
    actor_id: UUID,
    conversation_id: UUID,
    idempotency_key: str,
    operation: str,
    task_id: UUID | None,
    request_id: str,
) -> AgentTaskView | None:
    if operation == "create":
        statement = select(AgentTask.id).where(
            AgentTask.actor_id == actor_id,
            AgentTask.conversation_id == conversation_id,
            AgentTask.idempotency_key == idempotency_key,
        )
    elif task_id is None:
        return None
    elif operation == "input":
        statement = (
            select(AgentTask.id)
            .join(TaskStep, TaskStep.task_id == AgentTask.id)
            .where(
                AgentTask.id == task_id,
                AgentTask.actor_id == actor_id,
                AgentTask.conversation_id == conversation_id,
                TaskStep.step_type == "user_input",
                TaskStep.idempotency_key == idempotency_key,
            )
        )
    elif operation == "confirm":
        statement = (
            select(AgentTask.id)
            .join(ConfirmationChallenge, ConfirmationChallenge.task_id == AgentTask.id)
            .where(
                AgentTask.id == task_id,
                AgentTask.actor_id == actor_id,
                AgentTask.conversation_id == conversation_id,
                ConfirmationChallenge.actor_id == actor_id,
                ConfirmationChallenge.idempotency_key == idempotency_key,
            )
        )
    elif operation == "cancel":
        cancel_key = f"cancel:{_hash({'key': idempotency_key})}"
        statement = (
            select(AgentTask.id)
            .join(TaskStep, TaskStep.task_id == AgentTask.id)
            .where(
                AgentTask.id == task_id,
                AgentTask.actor_id == actor_id,
                AgentTask.conversation_id == conversation_id,
                TaskStep.step_type == "cancellation",
                TaskStep.idempotency_key == cancel_key,
            )
        )
    else:
        return None

    matched_task_id = session.scalar(statement.limit(1))
    if matched_task_id is None:
        return None
    return get_agent_task(
        session, actor_id=actor_id, task_id=matched_task_id, request_id=request_id
    )


def _invalidate_pending_challenges(
    session: Session, *, task: AgentTask, actor_id: UUID, request_id: str
) -> None:
    challenges = list(
        session.scalars(
            select(ConfirmationChallenge).where(
                ConfirmationChallenge.task_id == task.id,
                ConfirmationChallenge.status == "pending",
            )
        )
    )
    for challenge in challenges:
        challenge.status = "cancelled"
        execution = session.get(ToolExecution, challenge.tool_execution_id)
        if execution is not None:
            execution.status = "cancelled"
            execution.error_code = "superseded_by_new_input"
            execution.completed_at = utc_now()
            step = session.get(TaskStep, execution.step_id)
            if step is not None:
                step.status = "cancelled"
                step.error_code = "superseded_by_new_input"
                step.summary = "Pending confirmation was cancelled because the request changed."
                step.completed_at = utc_now()
        resource_type = "card" if challenge.card_id is not None else "subscription"
        resource_id = challenge.card_id or challenge.subscription_id
        _audit(
            session,
            actor_id=actor_id,
            event_type=f"{resource_type}.confirmation_invalidated",
            resource_type=resource_type,
            resource_id=resource_id,
            card_id=challenge.card_id,
            request_id=request_id,
            task_id=task.id,
            tool_execution_id=challenge.tool_execution_id,
            outcome="cancelled",
            before_state={"confirmation": "pending", "target_status": challenge.target_status},
            after_state={"confirmation": "cancelled"},
        )


def submit_task_input(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    request_text: str,
    idempotency_key: str,
    request_id: str,
    selection: ProviderSelection,
) -> AgentTaskView:
    input_hash = _hash({"request_text": request_text})
    prior_input = session.scalar(
        select(TaskStep).where(
            TaskStep.task_id == task_id, TaskStep.idempotency_key == idempotency_key
        )
    )
    if prior_input is not None:
        if prior_input.input_hash != input_hash:
            raise AgentIdempotencyConflictError
        return _task_view(session, actor_id=actor_id, task_id=task_id)

    with write_transaction(session, immediate=True):
        task = _owned_task(session, actor_id=actor_id, task_id=task_id)
        prior_input = session.scalar(
            select(TaskStep).where(
                TaskStep.task_id == task.id, TaskStep.idempotency_key == idempotency_key
            )
        )
        if prior_input is not None:
            if prior_input.input_hash != input_hash:
                raise AgentIdempotencyConflictError
            return _task_view(session, actor_id=actor_id, task_id=task_id)
        if task.status not in {"awaiting_input", "awaiting_confirmation"}:
            raise AgentTaskStateConflictError
        _invalidate_pending_challenges(session, task=task, actor_id=actor_id, request_id=request_id)
        before = task.status
        _transition(task, "planning")
        task.request_text = request_text
        task.error_code = None
        task.message = "正在根据补充信息更新任务。"
        sequence = _next_sequence(session, task.id)
        session.add(
            TaskStep(
                task_id=task.id,
                sequence=sequence,
                step_type="user_input",
                status="succeeded",
                summary="User supplied updated task instructions.",
                idempotency_key=idempotency_key,
                input_hash=input_hash,
                completed_at=utc_now(),
            )
        )
        session.add(
            TaskStep(
                task_id=task.id,
                sequence=sequence + 1,
                step_type="planner",
                status="running",
                summary=f"Replanning with {selection.mode} provider.",
            )
        )
        _audit(
            session,
            actor_id=actor_id,
            event_type="agent.task_input_received",
            resource_type="task",
            resource_id=task.id,
            request_id=request_id,
            task_id=task.id,
            outcome="succeeded",
            before_state={"status": before},
            after_state={"status": task.status},
        )
        conversation_id = task.conversation_id
        session.flush()

    return _run_task(
        session,
        actor_id=actor_id,
        task_id=task_id,
        request_text=request_text,
        conversation_id=conversation_id,
        request_id=request_id,
        selection=selection,
    )


def _task_audit(session: Session, *, actor_id: UUID, task_id: UUID) -> tuple[AuditSummaryView, ...]:
    _owned_task(session, actor_id=actor_id, task_id=task_id)
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.task_id == task_id, AuditEvent.actor_id == actor_id)
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
    )
    return tuple(
        AuditSummaryView(
            id=event.id,
            event_type=event.event_type,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            tool_execution_id=event.tool_execution_id,
            outcome=event.outcome,
            before_state=event.before_state,
            after_state=event.after_state,
            occurred_at=_utc(event.occurred_at),
        )
        for event in events
    )


def get_task_audit(
    session: Session, *, actor_id: UUID, task_id: UUID
) -> tuple[AuditSummaryView, ...]:
    return _task_audit(session, actor_id=actor_id, task_id=task_id)


def _mark_confirmation_rejected(
    session: Session,
    *,
    task: AgentTask,
    challenge: ConfirmationChallenge,
    execution: ToolExecution,
    request_id: str,
    error_code: str,
    outcome: str,
) -> None:
    before_task = task.status
    challenge.status = "invalidated" if error_code != "confirmation_expired" else "expired"
    execution.status = "failed"
    execution.error_code = error_code
    execution.result_summary = "Confirmation was rejected; no business state change was made."
    execution.result_data = {"status": "failed", "error_code": error_code}
    execution.completed_at = utc_now()
    step = session.get(TaskStep, execution.step_id)
    if step is not None:
        step.status = "failed"
        step.error_code = error_code
        step.summary = execution.result_summary
        step.completed_at = utc_now()
    if task.status not in {"failed", "cancelled", "completed"}:
        _transition(task, "failed")
    task.error_code = error_code
    resource_type = "card" if challenge.card_id is not None else "subscription"
    resource_id = challenge.card_id or challenge.subscription_id
    task.message = "确认已失效或不匹配；业务状态没有改变。"
    _audit(
        session,
        actor_id=task.actor_id,
        event_type=f"{resource_type}.confirmation_rejected",
        resource_type=resource_type,
        resource_id=resource_id,
        card_id=challenge.card_id,
        request_id=request_id,
        task_id=task.id,
        tool_execution_id=execution.id,
        outcome=outcome,
        before_state={"status": before_task, "confirmation": "pending"},
        after_state={
            "status": task.status,
            "confirmation": challenge.status,
            "error_code": error_code,
        },
    )


def confirm_task_operation(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    challenge_id: UUID,
    parameters_hash: str,
    idempotency_key: str,
    request_id: str,
) -> AgentTaskView:
    stale_error: Exception | None = None
    try:
        with write_transaction(session, immediate=True):
            task = _owned_task(session, actor_id=actor_id, task_id=task_id)
            challenge = session.scalar(
                select(ConfirmationChallenge).where(
                    ConfirmationChallenge.id == challenge_id,
                    ConfirmationChallenge.task_id == task.id,
                    ConfirmationChallenge.actor_id == actor_id,
                )
            )
            if challenge is None:
                raise AgentTaskNotFoundError
            execution = session.get(ToolExecution, challenge.tool_execution_id)
            if execution is None:
                raise AgentTaskNotFoundError
            if idempotency_key != challenge.idempotency_key:
                raise AgentIdempotencyConflictError
            if challenge.status == "consumed":
                if parameters_hash != challenge.parameters_hash:
                    raise AgentIdempotencyConflictError
                return _task_view(session, actor_id=actor_id, task_id=task.id)
            if challenge.status != "pending":
                raise AgentTaskStateConflictError
            if parameters_hash != challenge.parameters_hash:
                _mark_confirmation_rejected(
                    session,
                    task=task,
                    challenge=challenge,
                    execution=execution,
                    request_id=request_id,
                    error_code="confirmation_parameters_mismatch",
                    outcome="rejected",
                )
                session.flush()
                return _task_view(session, actor_id=actor_id, task_id=task.id)
            if _utc(challenge.expires_at) <= utc_now():
                _mark_confirmation_rejected(
                    session,
                    task=task,
                    challenge=challenge,
                    execution=execution,
                    request_id=request_id,
                    error_code="confirmation_expired",
                    outcome="expired",
                )
                session.flush()
                return _task_view(session, actor_id=actor_id, task_id=task.id)

            if challenge.subscription_id is not None:
                subscription = get_owned_subscription(
                    session,
                    actor_id=actor_id,
                    subscription_id=challenge.subscription_id,
                )
                if subscription is None:
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code="subscription_not_found",
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)
                normalized = {
                    "tool_name": challenge.tool_name,
                    "tool_version": challenge.tool_version,
                    "subscription_id": str(challenge.subscription_id),
                    "target_status": challenge.target_status,
                }
                expected_target = {
                    "subscription.pause": "paused",
                    "subscription.resume": "active",
                    "subscription.cancel": "cancelled",
                }.get(challenge.tool_name)
                if (
                    subscription.version != challenge.subscription_version
                    or _hash(normalized) != challenge.parameters_hash
                    or execution.input_hash != challenge.parameters_hash
                    or challenge.target_status != expected_target
                    or challenge.tool_version != TOOL_VERSION
                    or challenge.policy_version != SUBSCRIPTION_POLICY_VERSION
                    or execution.idempotency_key != challenge.idempotency_key
                ):
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code="subscription_version_conflict",
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)

                before_status = subscription.status
                before_version = subscription.version
                _transition(task, "running")
                execution.status = "running"
                challenge.status = "consumed"
                challenge.consumed_at = utc_now()
                changed = change_subscription_status(
                    session,
                    actor_id=actor_id,
                    subscription_id=subscription.id,
                    target_status=challenge.target_status,
                    request_id=request_id,
                    task_id=task.id,
                    tool_execution_id=execution.id,
                )
                execution.status = "succeeded"
                execution.result_data = {
                    "subscription": {
                        "id": str(changed.id),
                        "merchant": changed.merchant,
                        "amount_minor": changed.amount_minor,
                        "currency": changed.currency,
                        "billing_cycle": changed.billing_cycle,
                        "status": changed.status,
                        "next_charge_at": changed.next_charge_at.isoformat(),
                        "version": changed.version,
                    },
                    "status": "succeeded",
                }
                execution.result_summary = (
                    f"Subscription {changed.merchant} status changed to {changed.status}."
                )
                execution.completed_at = utc_now()
                step = session.get(TaskStep, execution.step_id)
                if step is not None:
                    step.status = "succeeded"
                    step.summary = execution.result_summary
                    step.completed_at = utc_now()
                _transition(task, "completed")
                action = {"paused": "已暂停", "active": "已恢复", "cancelled": "已取消"}[
                    changed.status
                ]
                task.message = f"{changed.merchant}自动续费{action}。"
                task.error_code = None
                _audit(
                    session,
                    actor_id=actor_id,
                    event_type="subscription.confirmation_consumed",
                    resource_type="subscription",
                    resource_id=subscription.id,
                    request_id=request_id,
                    task_id=task.id,
                    tool_execution_id=execution.id,
                    outcome="succeeded",
                    before_state={"status": before_status, "version": before_version},
                    after_state={"status": changed.status, "version": changed.version},
                )
                session.flush()
                return _task_view(session, actor_id=actor_id, task_id=task.id)

            card = get_owned_card(session, actor_id=actor_id, card_id=challenge.card_id)
            if card is None:
                _mark_confirmation_rejected(
                    session,
                    task=task,
                    challenge=challenge,
                    execution=execution,
                    request_id=request_id,
                    error_code="card_not_found",
                    outcome="rejected",
                )
                session.flush()
                return _task_view(session, actor_id=actor_id, task_id=task.id)
            normalized = {
                "tool_name": challenge.tool_name,
                "tool_version": challenge.tool_version,
                "card_id": str(challenge.card_id),
                "target_status": challenge.target_status,
            }
            expected_tool = (
                "card.freeze"
                if challenge.target_status == CardStatus.FROZEN.value
                else "card.unfreeze"
            )
            if (
                card.version != challenge.card_version
                or _hash(normalized) != challenge.parameters_hash
                or execution.input_hash != challenge.parameters_hash
                or challenge.tool_name != expected_tool
                or challenge.tool_version != TOOL_VERSION
                or challenge.policy_version != POLICY_VERSION
                or execution.idempotency_key != challenge.idempotency_key
            ):
                _mark_confirmation_rejected(
                    session,
                    task=task,
                    challenge=challenge,
                    execution=execution,
                    request_id=request_id,
                    error_code="card_version_conflict",
                    outcome="rejected",
                )
                session.flush()
                return _task_view(session, actor_id=actor_id, task_id=task.id)

            before_status = card.status.value
            before_version = card.version
            _transition(task, "running")
            execution.status = "running"
            challenge.status = "consumed"
            challenge.consumed_at = utc_now()
            if challenge.target_status == CardStatus.FROZEN.value:
                changed = freeze_card(
                    session,
                    actor_id=actor_id,
                    card_id=challenge.card_id,
                    request_id=request_id,
                    task_id=task.id,
                    tool_execution_id=execution.id,
                )
            elif challenge.target_status == CardStatus.ACTIVE.value:
                changed = unfreeze_card(
                    session,
                    actor_id=actor_id,
                    card_id=challenge.card_id,
                    request_id=request_id,
                    task_id=task.id,
                    tool_execution_id=execution.id,
                )
            else:
                raise AgentTaskStateConflictError
            execution.status = "succeeded"
            execution.result_data = {
                "card": _to_card_item(changed),
                "card_suffix": changed.card_suffix,
                "status": "succeeded",
            }
            execution.result_summary = (
                f"Card {changed.card_suffix} status changed to {changed.status.value}."
            )
            execution.completed_at = utc_now()
            step = session.get(TaskStep, execution.step_id)
            if step is not None:
                step.status = "succeeded"
                step.summary = execution.result_summary
                step.completed_at = utc_now()
            _transition(task, "completed")
            action = "冻结" if changed.status is CardStatus.FROZEN else "解冻"
            task.message = f"尾号 {changed.card_suffix} 的卡片已{action}。"
            task.error_code = None
            _audit(
                session,
                actor_id=actor_id,
                event_type="card.confirmation_consumed",
                resource_type="card",
                resource_id=card.id,
                card_id=card.id,
                request_id=request_id,
                task_id=task.id,
                tool_execution_id=execution.id,
                outcome="succeeded",
                before_state={"status": before_status, "version": before_version},
                after_state={"status": changed.status.value, "version": changed.version},
            )
            session.flush()
    except (CardWriteConflictError, SubscriptionWriteConflictError) as exc:
        stale_error = exc

    if stale_error is not None:
        with write_transaction(session, immediate=True):
            task = _owned_task(session, actor_id=actor_id, task_id=task_id)
            challenge = session.get(ConfirmationChallenge, challenge_id)
            if challenge is not None and challenge.status == "pending":
                execution = session.get(ToolExecution, challenge.tool_execution_id)
                if execution is not None:
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code=(
                            "subscription_version_conflict"
                            if challenge.subscription_id is not None
                            else "card_version_conflict"
                        ),
                        outcome="rejected",
                    )
        return _task_view(session, actor_id=actor_id, task_id=task_id)

    return _task_view(session, actor_id=actor_id, task_id=task_id)


def cancel_agent_task(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    idempotency_key: str,
    request_id: str,
) -> AgentTaskView:
    scoped_key = f"cancel:{_hash({'key': idempotency_key})}"
    input_hash = _hash({"action": "cancel"})
    with write_transaction(session, immediate=True):
        task = _owned_task(session, actor_id=actor_id, task_id=task_id)
        prior = session.scalar(
            select(TaskStep).where(
                TaskStep.task_id == task.id,
                TaskStep.idempotency_key == scoped_key,
            )
        )
        if prior is not None:
            if prior.step_type != "cancellation" or prior.input_hash != input_hash:
                raise AgentIdempotencyConflictError
            return _task_view(session, actor_id=actor_id, task_id=task_id)
        if task.status in {"completed", "failed", "cancelled"}:
            raise AgentTaskStateConflictError
        before = task.status
        _invalidate_pending_challenges(session, task=task, actor_id=actor_id, request_id=request_id)
        for step in session.scalars(
            select(TaskStep).where(TaskStep.task_id == task.id, TaskStep.status == "running")
        ):
            step.status = "cancelled"
            step.error_code = "task_cancelled"
            step.summary = "Step was cancelled before its side effect completed."
            step.completed_at = utc_now()
        _transition(task, "cancelled")
        task.message = "任务已取消；尚未确认的卡片操作没有执行。"
        session.add(
            TaskStep(
                task_id=task.id,
                sequence=_next_sequence(session, task.id),
                step_type="cancellation",
                status="cancelled",
                summary="User cancelled the task before its pending side effect.",
                idempotency_key=scoped_key,
                input_hash=input_hash,
                completed_at=utc_now(),
            )
        )
        _audit(
            session,
            actor_id=actor_id,
            event_type="agent.task_cancelled",
            resource_type="task",
            resource_id=task.id,
            request_id=request_id,
            task_id=task.id,
            outcome="cancelled",
            before_state={"status": before},
            after_state={"status": task.status},
        )
    return _task_view(session, actor_id=actor_id, task_id=task_id)


# Backward-compatible application name retained for existing integrations.
confirm_card_change = confirm_task_operation


__all__ = [
    "AgentIdempotencyConflictError",
    "AgentTaskNotFoundError",
    "AgentTaskStateConflictError",
    "AgentTaskView",
    "AuditSummaryView",
    "cancel_agent_task",
    "confirm_card_change",
    "confirm_task_operation",
    "create_agent_task",
    "get_agent_task",
    "get_agent_task_by_idempotency_key",
    "get_recent_agent_task",
    "get_task_audit",
    "submit_task_input",
]
