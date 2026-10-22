import hashlib
import json
import logging
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from finorch_api.agent.context import ToolCallContext
from finorch_api.agent.intent import is_planning_only_request
from finorch_api.agent.providers import ProviderSelection
from finorch_api.agent.registry import (
    POLICY_VERSION,
    SUBSCRIPTION_POLICY_VERSION,
    TOOL_VERSION,
    ToolTargetAmbiguousError,
    build_tool_registry,
    card_result_payload,
)
from finorch_api.agent.runtime import (
    AgentProviderError,
    AgentRunResult,
    AgentRuntime,
    ModelToolCall,
    ToolDispatchResult,
    ToolExecutionError,
    ToolSpec,
)
from finorch_api.application.agent_workflow import (
    has_completed_tool_execution,
    invalid_tool_input_name,
    missing_explicit_write_parameters_message,
    missing_payday_parameters_message,
    missing_requested_write_tools,
    missing_write_input_message,
    requires_transfer_before_investment,
    split_proposal_mismatch_message,
    task_progress_context,
    tool_input_clarification_message,
    unknown_requested_transfer_payee_message,
    unsuitable_requested_investment_message,
)
from finorch_api.application.cards import (
    CardNotFoundError,
    CardWriteConflictError,
    freeze_card,
    unfreeze_card,
)
from finorch_api.application.errors import BankingRuleError
from finorch_api.application.investments import confirm_order
from finorch_api.application.subscriptions import (
    SubscriptionAmbiguousError,
    SubscriptionNotFoundError,
    SubscriptionWriteConflictError,
    change_subscription_status,
    get_owned_subscription,
)
from finorch_api.application.transactions import write_transaction
from finorch_api.application.transfers import confirm_split, confirm_transfer
from finorch_api.domain.cards import CardStatus, InvalidCardTransition
from finorch_api.domain.subscriptions import (
    InvalidSubscriptionTransition,
)
from finorch_api.infrastructure.models import (
    Account,
    AgentTask,
    AuditEvent,
    ConfirmationChallenge,
    InvestmentOrder,
    InvestmentProduct,
    SplitBill,
    SplitParticipant,
    TaskStep,
    ToolExecution,
    Transfer,
    utc_now,
)
from finorch_api.infrastructure.persistence.cards import get_owned_card
from finorch_api.security.circuit import (
    active_write_hold,
    record_safety_signal,
    signal_category,
)
from finorch_api.security.verification import challenge_risk, consume_demo_code
from finorch_api.security.write_intent import (
    transfer_phone_matches_request,
    user_authorized_write,
)

logger = logging.getLogger("finorch.agent")

_TASK_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"planning", "cancelled"},
    "planning": {"awaiting_input", "awaiting_confirmation", "running", "failed", "cancelled"},
    "awaiting_input": {"planning", "cancelled"},
    "awaiting_confirmation": {"running", "planning", "cancelled", "failed"},
    "running": {"awaiting_input", "awaiting_confirmation", "completed", "failed", "cancelled"},
    "completed": set(),
    "failed": {"planning", "awaiting_input"},
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
    details: dict[str, Any] | None = None
    risk_level: str = "yellow"
    confirmation_method: str = "explicit"
    risk_rules: tuple[str, ...] = ()


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
    if isinstance(exception, BankingRuleError):
        return exception.code, exception.public_message
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
    needs_user_input = code == "tool_input_invalid"
    if not needs_user_input and task.status not in {"failed", "cancelled", "completed"}:
        _transition(task, "failed")
    task.error_code = None if needs_user_input else code
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
        after_state={
            "status": task.status,
            "error_code": task.error_code,
            "tool_error_code": code,
        },
    )
    record_safety_signal(
        session,
        actor_id=actor_id,
        code=code,
        request_id=request_id,
        task_id=task.id,
        tool_execution_id=execution.id,
    )
    return ToolDispatchResult("failed", execution.result_data, message, code)


def _record_workflow_block(
    session: Session,
    *,
    task: AgentTask,
    step: TaskStep,
    execution: ToolExecution,
    actor_id: UUID,
    request_id: str,
    code: str,
    message: str,
) -> ToolDispatchResult:
    """Persist a rejected out-of-order tool call without ending the planner turn."""
    execution.status = "failed"
    execution.error_code = code
    execution.result_summary = message
    execution.result_data = {"status": "blocked", "error_code": code}
    execution.completed_at = utc_now()
    step.status = "failed"
    step.error_code = code
    step.summary = message
    step.completed_at = utc_now()
    _audit(
        session,
        actor_id=actor_id,
        event_type="agent.workflow_step_blocked",
        resource_type="task",
        resource_id=task.id,
        request_id=request_id,
        task_id=task.id,
        tool_execution_id=execution.id,
        outcome="blocked",
        before_state={"status": task.status},
        after_state={"status": task.status, "tool_name": execution.tool_name, "error_code": code},
    )
    return ToolDispatchResult("blocked", execution.result_data, message, code)


def _successful_tool_result(
    session: Session, *, task_id: UUID, tool_name: str
) -> dict[str, Any] | None:
    return session.scalar(
        select(ToolExecution.result_data)
        .where(
            ToolExecution.task_id == task_id,
            ToolExecution.tool_name == tool_name,
            ToolExecution.status == "succeeded",
        )
        .order_by(ToolExecution.created_at.desc(), ToolExecution.id.desc())
        .limit(1)
    )


def _workflow_write_block_reason(
    session: Session, *, task: AgentTask, tool_name: str, parsed: BaseModel
) -> tuple[str, str] | None:
    """Enforce the persisted transfer, planning, and suitability dependencies."""
    if is_planning_only_request(task.request_text):
        return "workflow_write_not_authorized", "本次只请求资金测算，没有授权创建或执行业务操作。"
    if not requires_transfer_before_investment(task.request_text):
        return None

    plan = _successful_tool_result(session, task_id=task.id, tool_name="finance.payday_plan")
    products = _successful_tool_result(session, task_id=task.id, tool_name="investment.products")
    items = products.get("items", []) if isinstance(products, dict) else []
    suitable_items = (
        [item for item in items if isinstance(item, dict) and item.get("suitable") is True]
        if isinstance(items, list)
        else []
    )
    is_payday = any(
        phrase in task.request_text.casefold()
        for phrase in ("发薪", "工资", "薪资", "收入到账", "资金调度")
    )

    if tool_name == "transfer.create":
        if is_payday and not isinstance(plan, dict):
            return "workflow_step_not_ready", "请先完成服务端资金计划，再提出转账确认。"
        if is_payday and isinstance(plan, dict):
            if getattr(parsed, "recipient_name", None) != plan.get("recipient_name") or getattr(
                parsed, "amount_minor", None
            ) != plan.get("transfer_amount_minor"):
                return (
                    "workflow_step_mismatch",
                    "转账对象或金额与服务端资金计划不一致，已阻止确认。",
                )
        if not isinstance(products, dict):
            return "workflow_step_not_ready", "请先查询理财产品适当性，再提出转账确认。"
        if not suitable_items:
            return (
                "no_suitable_investment_product",
                "没有适当的模拟理财产品，未提出转账或申购确认。",
            )
        requested_product = next(
            (
                item
                for item in items
                if isinstance(item, dict) and item.get("name") and item["name"] in task.request_text
            ),
            None,
        )
        if requested_product is not None and requested_product.get("suitable") is not True:
            return "risk_mismatch", "所选模拟产品不符合当前风险等级，未提出转账确认。"

    if tool_name == "investment.buy":
        transfer = _successful_tool_result(session, task_id=task.id, tool_name="transfer.create")
        transfer_data = transfer.get("transfer", transfer) if isinstance(transfer, dict) else None
        if not isinstance(transfer_data, dict) or transfer_data.get("status") != "executed":
            return "workflow_step_not_ready", "转账尚未确认并成功执行，不能提出后续申购确认。"
        if isinstance(plan, dict) and (
            transfer_data.get("payee_name") != plan.get("recipient_name")
            or transfer_data.get("amount_minor") != plan.get("transfer_amount_minor")
        ):
            return "workflow_step_mismatch", "已执行的转账与服务端资金计划不一致，已阻止后续申购。"
        if isinstance(plan, dict) and getattr(parsed, "amount_minor", 0) > plan.get(
            "investment_budget_minor", 0
        ):
            return "investment_budget_exceeded", "申购金额超过服务端计算的可投资额度。"
        product_name = getattr(parsed, "product_name", None)
        product = (
            next(
                (
                    item
                    for item in items
                    if isinstance(item, dict) and item.get("name") == product_name
                ),
                None,
            )
            if isinstance(items, list)
            else None
        )
        if product is None or product.get("suitable") is not True:
            return "investment_suitability_not_verified", "申购产品尚未通过服务端适当性查询。"

    return None


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
        if task.status not in {"planning", "running"}:
            return ToolDispatchResult(
                "failed",
                {"status": "cancelled", "error_code": "task_not_running"},
                "任务已结束，没有执行新的工具调用。",
                "task_not_running",
            )

        tool_name = call.name[:80]
        raw_args = call.arguments[:2000]
        normalized_input = parsed.model_dump(mode="json") if parsed is not None else raw_args
        input_hash = _hash(normalized_input)
        if (
            spec is not None
            and parsed is not None
            and validation_error is None
            and spec.permission_level != "read_only"
        ):
            prior_success = session.scalar(
                select(ToolExecution)
                .join(TaskStep, TaskStep.id == ToolExecution.step_id)
                .where(
                    ToolExecution.task_id == task.id,
                    ToolExecution.tool_name == spec.name,
                    (TaskStep.input_hash == input_hash) | (ToolExecution.input_hash == input_hash),
                    ToolExecution.status == "succeeded",
                )
                .order_by(ToolExecution.created_at.desc(), ToolExecution.id.desc())
                .limit(1)
            )
            if prior_success is not None:
                _audit(
                    session,
                    actor_id=actor_id,
                    event_type="agent.duplicate_write_suppressed",
                    resource_type="task",
                    resource_id=task.id,
                    request_id=request_id,
                    task_id=task.id,
                    tool_execution_id=prior_success.id,
                    outcome="succeeded",
                    after_state={"tool_name": spec.name, "duplicate_suppressed": True},
                )
                return ToolDispatchResult(
                    "succeeded",
                    prior_success.result_data or {"status": "succeeded"},
                    prior_success.result_summary,
                )

        sequence = _next_sequence(session, task.id)
        idempotency_key = f"tool:{task.id}:{sequence}"
        step = TaskStep(
            task_id=task.id,
            sequence=sequence,
            step_type="tool",
            status="running",
            summary=f"Validating and running {tool_name}.",
            tool_name=tool_name,
            input_hash=input_hash,
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

        if spec is not None and spec.permission_level != "read_only":
            hold_until = active_write_hold(session, actor_id=actor_id)
            if hold_until is not None:
                return _record_tool_failure(
                    session,
                    task=task,
                    step=step,
                    execution=execution,
                    actor_id=actor_id,
                    request_id=request_id,
                    error=ToolExecutionError(
                        "safety_hold_active", "模拟安全限制暂时阻止写操作，请稍后再试。"
                    ),
                )

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

        if spec.name == "transfer.split_create" and parsed is not None:
            mismatch = split_proposal_mismatch_message(task.request_text, parsed)
            if mismatch is not None:
                return _record_tool_failure(
                    session,
                    task=task,
                    step=step,
                    execution=execution,
                    actor_id=actor_id,
                    request_id=request_id,
                    error=ToolExecutionError("tool_input_invalid", mismatch),
                )

        if spec.permission_level != "read_only" and not user_authorized_write(
            task.request_text, spec.name
        ):
            return _record_tool_failure(
                session,
                task=task,
                step=step,
                execution=execution,
                actor_id=actor_id,
                request_id=request_id,
                error=ToolExecutionError(
                    "write_not_requested", "用户没有授权这项写操作，未创建确认请求。"
                ),
            )

        if spec.name in {"transfer.create", "transfer.schedule"} and not (
            transfer_phone_matches_request(
                task.request_text, getattr(parsed, "recipient_phone", None)
            )
        ):
            return _record_tool_failure(
                session,
                task=task,
                step=step,
                execution=execution,
                actor_id=actor_id,
                request_id=request_id,
                error=ToolExecutionError(
                    "transfer_target_mismatch", "收款手机号与用户请求不一致，未创建确认请求。"
                ),
            )

        if spec.permission_level != "read_only" and parsed is not None:
            block = _workflow_write_block_reason(
                session, task=task, tool_name=spec.name, parsed=parsed
            )
            if block is not None:
                return _record_workflow_block(
                    session,
                    task=task,
                    step=step,
                    execution=execution,
                    actor_id=actor_id,
                    request_id=request_id,
                    code=block[0],
                    message=block[1],
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
            BankingRuleError,
            InvalidSubscriptionTransition,
            ValidationError,
            ToolExecutionError,
        ) as exc:
            if isinstance(exc, ValidationError):
                logger.warning(
                    "Agent tool result failed schema validation",
                    extra={
                        "tool_name": spec.name,
                        "validation_fields": [
                            ".".join(str(part) for part in error.get("loc", ()))
                            for error in exc.errors(include_input=False)
                        ],
                    },
                )
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
                "executed": "转账",
                "scheduled": "创建定时转账",
                "open": "创建分账",
                "settled": "模拟收取分账",
            }.get(target_status, "变更")
            label = str(result_data.get("resource_label", "")).strip()
            if resource_type == "card":
                target = f"尾号 {result_data['card_suffix']} 的银行卡"
            elif resource_type == "subscription":
                target = f"{label} 自动续费"
            elif resource_type == "transfer":
                target = f"给{label}的模拟转账"
            elif resource_type == "split":
                target = f"{label} AA 分账"
            elif resource_type == "investment_order":
                action = "模拟申购" if result_data.get("order_type") == "buy" else "模拟赎回"
                target = f"{label}理财产品"
            else:
                target = label
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
        elif challenge.transfer_id is not None:
            transfer = session.scalar(
                select(Transfer).where(
                    Transfer.id == challenge.transfer_id, Transfer.actor_id == actor_id
                )
            )
            if transfer is not None:
                source = session.get(Account, transfer.source_account_id)
                confirmation = ConfirmationView(
                    id=challenge.id,
                    resource_type="transfer",
                    resource_id=transfer.id,
                    resource_label=transfer.payee_name,
                    resource_version=challenge.transfer_version or transfer.version,
                    current_status=transfer.status,
                    target_status=challenge.target_status,
                    parameters_hash=challenge.parameters_hash,
                    idempotency_key=challenge.idempotency_key,
                    expires_at=_utc(challenge.expires_at),
                    policy_version=challenge.policy_version,
                    tool_name=challenge.tool_name,
                    tool_version=challenge.tool_version,
                    details={
                        "amount_minor": transfer.amount_minor,
                        "currency": transfer.currency,
                        "transfer_type": transfer.transfer_type,
                        "scheduled_at": _utc(transfer.scheduled_at).isoformat()
                        if transfer.scheduled_at
                        else None,
                        "source_account_label": source.label if source else "模拟账户",
                        "payee_name": transfer.payee_name,
                        "remark": transfer.remark,
                    },
                )
        elif challenge.split_bill_id is not None:
            bill = session.scalar(
                select(SplitBill).where(
                    SplitBill.id == challenge.split_bill_id, SplitBill.actor_id == actor_id
                )
            )
            if bill is not None:
                participants = list(
                    session.scalars(
                        select(SplitParticipant)
                        .where(SplitParticipant.split_bill_id == bill.id)
                        .order_by(SplitParticipant.sequence)
                    )
                )
                confirmation = ConfirmationView(
                    id=challenge.id,
                    resource_type="split",
                    resource_id=bill.id,
                    resource_label=bill.title,
                    resource_version=challenge.split_bill_version or bill.version,
                    current_status=bill.status,
                    target_status=challenge.target_status,
                    parameters_hash=challenge.parameters_hash,
                    idempotency_key=challenge.idempotency_key,
                    expires_at=_utc(challenge.expires_at),
                    policy_version=challenge.policy_version,
                    tool_name=challenge.tool_name,
                    tool_version=challenge.tool_version,
                    details={
                        "total_amount_minor": bill.total_amount_minor,
                        "currency": bill.currency,
                        "participants": [
                            {
                                "display_name": item.display_name,
                                "amount_minor": item.amount_minor,
                                "status": item.status,
                            }
                            for item in participants
                        ],
                    },
                )
        elif challenge.investment_order_id is not None:
            order = session.scalar(
                select(InvestmentOrder).where(
                    InvestmentOrder.id == challenge.investment_order_id,
                    InvestmentOrder.actor_id == actor_id,
                )
            )
            if order is not None:
                product = session.get(InvestmentProduct, order.product_id)
                account = session.get(Account, order.account_id)
                confirmation = ConfirmationView(
                    id=challenge.id,
                    resource_type="investment_order",
                    resource_id=order.id,
                    resource_label=product.name if product else "模拟理财产品",
                    resource_version=challenge.investment_order_version or order.version,
                    current_status=order.status,
                    target_status=challenge.target_status,
                    parameters_hash=challenge.parameters_hash,
                    idempotency_key=challenge.idempotency_key,
                    expires_at=_utc(challenge.expires_at),
                    policy_version=challenge.policy_version,
                    tool_name=challenge.tool_name,
                    tool_version=challenge.tool_version,
                    details={
                        "order_type": order.order_type,
                        "amount_minor": order.amount_minor,
                        "currency": order.currency,
                        "units_micros": order.units_micros,
                        "risk_level": product.risk_level if product else None,
                        "account_label": account.label if account else "模拟账户",
                    },
                )
    if confirmation is not None and challenge is not None:
        decision = challenge_risk(session, challenge, utc_now())
        confirmation = replace(
            confirmation,
            risk_level=decision.level,
            confirmation_method=decision.confirmation_method,
            risk_rules=decision.rules,
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
        recovered_payee_clarification = (
            task.status == "failed"
            and status == "awaiting_input"
            and task.error_code == "payee_not_found"
        )
        # A request can finish after another request has cancelled the task or
        # after a concurrent continuation has created a pending confirmation.
        # Preserve that committed state and its user-facing message.
        if task.status in {"completed", "cancelled"} or (
            task.status == "awaiting_confirmation" and status != "awaiting_confirmation"
        ):
            return
        if task.status not in {"awaiting_confirmation", "completed", "failed", "cancelled"} or (
            recovered_payee_clarification
        ):
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
        if error_code and signal_category(error_code) == "provider_failure":
            record_safety_signal(
                session,
                actor_id=actor_id,
                code=error_code,
                request_id=request_id,
                task_id=task.id,
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
    continuation: bool = False,
) -> AgentTaskView:
    payday_clarification = missing_payday_parameters_message(request_text)
    if payday_clarification:
        _finalize_run(
            session,
            actor_id=actor_id,
            task_id=task_id,
            request_id=request_id,
            status="awaiting_input",
            message=payday_clarification,
            error_code=None,
        )
        return _task_view(session, actor_id=actor_id, task_id=task_id)

    write_clarification = missing_explicit_write_parameters_message(request_text)
    if write_clarification:
        _finalize_run(
            session,
            actor_id=actor_id,
            task_id=task_id,
            request_id=request_id,
            status="awaiting_input",
            message=write_clarification,
            error_code=None,
        )
        return _task_view(session, actor_id=actor_id, task_id=task_id)

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
    trusted_context.update(task_progress_context(session, actor_id=actor_id, task_id=task_id))
    requires_ordered_transfer = requires_transfer_before_investment(request_text)
    if requires_ordered_transfer:
        progress = trusted_context.get("task_progress", {})
        succeeded_names = {
            item.get("tool_name")
            for item in progress.get("tools", [])
            if isinstance(item, dict) and item.get("status") == "succeeded"
        }
        if "transfer.create" not in succeeded_names:
            trusted_context["task_progress"] = {
                **progress,
                "required_next_tools": ["transfer.create"],
            }
    registry = build_tool_registry()

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
        result = AgentRunResult(
            status="running",
            message="正在处理任务。",
            error_code=None,
            executed_tools=0,
        )
        for replan_count in range(3):
            result = AgentRuntime(selection.provider, max_steps=8).run(
                request_text=request_text,
                trusted_context=trusted_context,
                registry=registry,
                dispatch=dispatch,
                continuation=continuation or replan_count > 0,
            )
            if (
                requires_ordered_transfer
                and result.error_code == "agent_required_tool_mismatch"
                and replan_count < 2
            ):
                progress = task_progress_context(session, actor_id=actor_id, task_id=task_id).get(
                    "task_progress", {}
                )
                trusted_context["task_progress"] = {
                    **progress,
                    "required_next_tools": ["transfer.create"],
                }
                continue
            if result.status != "completed":
                break
            current_progress = task_progress_context(
                session, actor_id=actor_id, task_id=task_id
            ).get("task_progress", {})
            missing_tools = missing_requested_write_tools(request_text, current_progress)
            if not missing_tools or replan_count == 2:
                break
            clarification = missing_write_input_message(
                request_text, current_progress, missing_tools
            )
            if clarification is None:
                clarification = unknown_requested_transfer_payee_message(
                    request_text, current_progress
                )
            if clarification:
                result = AgentRunResult(
                    status="awaiting_input",
                    message=clarification,
                    error_code=None,
                    executed_tools=result.executed_tools,
                )
                break
            trusted_context["task_progress"] = {
                **current_progress,
                "required_next_tools": list(missing_tools),
            }
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
    except Exception as exc:
        # Providers and tool adapters are extension points. Unexpected errors
        # must not leave a persisted task looking active forever. Any current
        # write unit of work has already rolled back before control reaches
        # here; previously committed steps remain visible as partial progress.
        session.rollback()
        logger.error(
            "Agent run failed unexpectedly",
            extra={"task_id": str(task_id), "error_type": type(exc).__name__},
        )
        _finalize_run(
            session,
            actor_id=actor_id,
            task_id=task_id,
            request_id=request_id,
            status="failed",
            message="任务处理遇到内部错误；已完成步骤保留，其余步骤没有确认成功。",
            error_code="agent_runtime_error",
        )
        return _task_view(session, actor_id=actor_id, task_id=task_id)

    task_progress = task_progress_context(session, actor_id=actor_id, task_id=task_id).get(
        "task_progress", {}
    )
    invalid_tool_name = invalid_tool_input_name(task_progress)
    if result.error_code == "tool_input_invalid" and invalid_tool_name:
        result = AgentRunResult(
            status="awaiting_input",
            message=tool_input_clarification_message(invalid_tool_name),
            error_code=None,
            executed_tools=result.executed_tools,
        )
    payday_clarification = missing_payday_parameters_message(request_text)
    if payday_clarification and result.status in {"completed", "awaiting_input"}:
        result = AgentRunResult(
            status="awaiting_input",
            message=payday_clarification,
            error_code=None,
            executed_tools=result.executed_tools,
        )
    clarification = unknown_requested_transfer_payee_message(request_text, task_progress)
    if not payday_clarification and clarification and result.status in {"completed", "failed"}:
        result = AgentRunResult(
            status="awaiting_input",
            message=clarification,
            error_code=None,
            executed_tools=result.executed_tools,
        )
    elif result.status == "completed":
        unsuitable_investment = unsuitable_requested_investment_message(request_text, task_progress)
        if unsuitable_investment:
            result = AgentRunResult(
                status="failed",
                message=unsuitable_investment,
                error_code="risk_mismatch",
                executed_tools=result.executed_tools,
            )
        else:
            missing_tools = missing_requested_write_tools(request_text, task_progress)
            if missing_tools:
                clarification = missing_write_input_message(
                    request_text, task_progress, missing_tools
                )
                if clarification:
                    result = AgentRunResult(
                        status="awaiting_input",
                        message=clarification,
                        error_code=None,
                        executed_tools=result.executed_tools,
                    )
                else:
                    result = AgentRunResult(
                        status="failed",
                        message="请求中的操作步骤尚未由业务工具完成，因此任务未标记为完成。",
                        error_code="agent_workflow_incomplete",
                        executed_tools=result.executed_tools,
                    )

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


def continue_confirmed_task(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    request_id: str,
    selection: ProviderSelection,
) -> AgentTaskView:
    with write_transaction(session, immediate=True):
        task = _owned_task(session, actor_id=actor_id, task_id=task_id)
        if task.status != "running":
            return _task_view(session, actor_id=actor_id, task_id=task_id)
        latest_planner = session.scalar(
            select(TaskStep)
            .where(TaskStep.task_id == task.id, TaskStep.step_type == "planner")
            .order_by(TaskStep.sequence.desc())
            .limit(1)
        )
        if latest_planner is not None and latest_planner.status == "running":
            return _task_view(session, actor_id=actor_id, task_id=task_id)
        planner_count = (
            session.scalar(
                select(func.count())
                .select_from(TaskStep)
                .where(
                    TaskStep.task_id == task.id,
                    TaskStep.step_type == "planner",
                )
            )
            or 0
        )
        if planner_count >= 6:
            _transition(task, "failed")
            task.error_code = "agent_continuation_limit_exceeded"
            task.message = "任務已達到續跑上限，已完成的操作保留，未完成的操作沒有執行。"
            return _task_view(session, actor_id=actor_id, task_id=task_id)
        task.message = "正在继续处理原任务。"
        task.error_code = None
        session.add(
            TaskStep(
                task_id=task.id,
                sequence=_next_sequence(session, task.id),
                step_type="planner",
                status="running",
                summary=f"Continuing with {selection.mode} provider.",
            )
        )
        _audit(
            session,
            actor_id=actor_id,
            event_type="agent.workflow_continued",
            resource_type="task",
            resource_id=task.id,
            request_id=request_id,
            task_id=task.id,
            outcome="succeeded",
            before_state={"status": task.status},
            after_state={"status": "running", "planner_count": planner_count + 1},
        )
        request_text = task.request_text
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
        continuation=True,
    )


def _challenge_resource(challenge: ConfirmationChallenge) -> tuple[str, UUID]:
    for kind, resource_id in (
        ("card", challenge.card_id),
        ("subscription", challenge.subscription_id),
        ("transfer", challenge.transfer_id),
        ("split", challenge.split_bill_id),
        ("investment_order", challenge.investment_order_id),
    ):
        if resource_id is not None:
            return kind, resource_id
    raise AgentTaskStateConflictError("Confirmation has no resource.")


def _cancel_unexecuted_proposal(
    session: Session, challenge: ConfirmationChallenge
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    resource: Transfer | SplitBill | InvestmentOrder | None = None
    if challenge.transfer_id is not None and challenge.target_status != "cancelled":
        resource = session.get(Transfer, challenge.transfer_id)
    elif challenge.split_bill_id is not None and challenge.target_status == "open":
        resource = session.get(SplitBill, challenge.split_bill_id)
    elif challenge.investment_order_id is not None:
        resource = session.get(InvestmentOrder, challenge.investment_order_id)

    if resource is None or resource.status != "awaiting_confirmation":
        return None, None
    before = {"status": resource.status, "version": resource.version}
    resource.status = "cancelled"
    session.flush()
    return before, {"status": resource.status, "version": resource.version}


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
        resource_type, resource_id = _challenge_resource(challenge)
        resource_before, resource_after = _cancel_unexecuted_proposal(session, challenge)
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
            before_state={
                "task_status": "awaiting_confirmation",
                "confirmation": "pending",
                "resource": resource_before,
            },
            after_state={
                "task_status": "failed",
                "confirmation": "expired",
                "resource": resource_after,
            },
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
        resource_type, resource_id = _challenge_resource(challenge)
        resource_before, resource_after = _cancel_unexecuted_proposal(session, challenge)
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
            before_state={
                "confirmation": "pending",
                "target_status": challenge.target_status,
                "resource": resource_before,
            },
            after_state={"confirmation": "cancelled", "resource": resource_after},
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
        resumable_partial_task = task.status in {"failed", "awaiting_input"} and (
            has_completed_tool_execution(session, task_id=task.id)
        )
        if (
            task.status not in {"awaiting_input", "awaiting_confirmation"}
            and not resumable_partial_task
        ):
            raise AgentTaskStateConflictError
        if resumable_partial_task or task.status in {"awaiting_input", "awaiting_confirmation"}:
            continued_request = f"{task.request_text}\n\n用户补充：{request_text}"
            if len(continued_request) > 1000:
                raise AgentTaskStateConflictError
            request_text = continued_request
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
        continuation = resumable_partial_task or has_completed_tool_execution(
            session, task_id=task.id
        )
        session.flush()

    return _run_task(
        session,
        actor_id=actor_id,
        task_id=task_id,
        request_text=request_text,
        conversation_id=conversation_id,
        request_id=request_id,
        selection=selection,
        continuation=continuation,
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
    resource_type, resource_id = _challenge_resource(challenge)
    resource_before, resource_after = _cancel_unexecuted_proposal(session, challenge)
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
        before_state={
            "status": before_task,
            "confirmation": "pending",
            "resource": resource_before,
        },
        after_state={
            "status": task.status,
            "confirmation": challenge.status,
            "error_code": error_code,
            "resource": resource_after,
        },
    )


def _complete_confirmed_resource(
    session: Session,
    *,
    actor_id: UUID,
    task: AgentTask,
    challenge: ConfirmationChallenge,
    execution: ToolExecution,
    request_id: str,
    resource_type: str,
    resource_id: UUID,
    result_data: dict[str, Any],
    result_summary: str,
    user_message: str,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
) -> AgentTaskView:
    result_data["status"] = "succeeded"
    execution.status = "succeeded"
    execution.result_data = result_data
    execution.result_summary = result_summary
    execution.completed_at = utc_now()
    step = session.get(TaskStep, execution.step_id)
    if step is not None:
        step.status = "succeeded"
        step.summary = result_summary
        step.completed_at = utc_now()
    task.message = user_message
    task.error_code = None
    _audit(
        session,
        actor_id=actor_id,
        event_type=f"{resource_type}.confirmation_consumed",
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        task_id=task.id,
        tool_execution_id=execution.id,
        outcome="succeeded",
        before_state=before_state,
        after_state=after_state,
    )
    session.flush()
    return _task_view(session, actor_id=actor_id, task_id=task.id)


def confirm_task_operation(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    challenge_id: UUID,
    parameters_hash: str,
    idempotency_key: str,
    request_id: str,
    verification_code: str | None = None,
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

            hold_until = active_write_hold(session, actor_id=actor_id)
            if hold_until is not None:
                task.error_code = "safety_hold_active"
                task.message = "模拟安全限制暂时阻止写操作；已完成的操作不会撤销。"
                _audit(
                    session,
                    actor_id=actor_id,
                    event_type="security.write_hold_enforced",
                    resource_type="confirmation",
                    resource_id=challenge.id,
                    request_id=request_id,
                    task_id=task.id,
                    tool_execution_id=execution.id,
                    outcome="blocked",
                    after_state={"expires_at": hold_until.isoformat()},
                )
                session.flush()
                return _task_view(session, actor_id=actor_id, task_id=task.id)

            decision = challenge_risk(session, challenge, utc_now())
            verification_error = None
            if decision.level == "red":
                verification_error = consume_demo_code(
                    session,
                    challenge=challenge,
                    decision=decision,
                    code=verification_code,
                    now=utc_now(),
                )
            _audit(
                session,
                actor_id=actor_id,
                event_type="security.risk_decision",
                resource_type="confirmation",
                resource_id=challenge.id,
                request_id=request_id,
                task_id=task.id,
                tool_execution_id=execution.id,
                outcome="rejected" if verification_error else "authorized",
                before_state=None,
                after_state={
                    "level": decision.level,
                    "rules": list(decision.rules),
                    "method": decision.confirmation_method,
                    "policy_version": decision.policy_version,
                    "verification_result": verification_error or "accepted",
                },
            )
            if verification_error:
                record_safety_signal(
                    session,
                    actor_id=actor_id,
                    code=verification_error,
                    request_id=request_id,
                    task_id=task.id,
                    tool_execution_id=execution.id,
                )
                task.error_code = verification_error
                task.message = "此操作需要完成模拟二次验证。"
                session.flush()
                return _task_view(session, actor_id=actor_id, task_id=task.id)
            task.error_code = None

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

            if challenge.transfer_id is not None:
                transfer = session.scalar(
                    select(Transfer).where(
                        Transfer.id == challenge.transfer_id, Transfer.actor_id == actor_id
                    )
                )
                if transfer is None:
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code="transfer_not_found",
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)
                target = challenge.target_status
                is_cancel = target == "cancelled"
                expected_tool = (
                    "transfer.cancel_scheduled"
                    if is_cancel
                    else "transfer.schedule"
                    if target == "scheduled"
                    else "transfer.create"
                )
                normalized = (
                    {
                        "tool_name": challenge.tool_name,
                        "tool_version": challenge.tool_version,
                        "transfer_id": str(transfer.id),
                        "target_status": "cancelled",
                        "transfer_version": transfer.version,
                    }
                    if is_cancel
                    else {
                        "tool_name": challenge.tool_name,
                        "tool_version": challenge.tool_version,
                        "transfer_id": str(transfer.id),
                        "source_account_id": str(transfer.source_account_id),
                        "destination_account_id": str(transfer.destination_account_id),
                        "payee_id": str(transfer.payee_id),
                        "remark": transfer.remark,
                        "amount_minor": transfer.amount_minor,
                        "currency": transfer.currency,
                        "transfer_type": transfer.transfer_type,
                        "scheduled_at": _utc(transfer.scheduled_at).isoformat()
                        if transfer.scheduled_at
                        else None,
                        "target_status": target,
                    }
                )
                expected_state = "scheduled" if is_cancel else "awaiting_confirmation"
                if (
                    transfer.version != challenge.transfer_version
                    or transfer.status != expected_state
                    or _hash(normalized) != challenge.parameters_hash
                    or execution.input_hash != challenge.parameters_hash
                    or challenge.tool_name != expected_tool
                    or challenge.tool_version != TOOL_VERSION
                    or challenge.policy_version != "transfer-confirmation-v1"
                    or execution.idempotency_key != challenge.idempotency_key
                    or (target == "executed" and transfer.transfer_type != "immediate")
                    or (target == "scheduled" and transfer.transfer_type != "scheduled")
                ):
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code="transfer_version_conflict",
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)

                before_state = {"status": transfer.status, "version": transfer.version}
                _transition(task, "running")
                execution.status = "running"
                challenge.status = "consumed"
                challenge.consumed_at = utc_now()
                try:
                    with session.begin_nested():
                        changed = confirm_transfer(
                            session,
                            actor_id=actor_id,
                            transfer_id=transfer.id,
                            target_status=target,
                            request_id=request_id,
                            task_id=task.id,
                            tool_execution_id=execution.id,
                        )
                except BankingRuleError as exc:
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code=exc.code,
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)
                after_state = {"status": changed.status, "version": changed.version}
                result_data = json.loads(
                    json.dumps(asdict(changed), ensure_ascii=False, default=str)
                )
                result_data["transfer"] = result_data.copy()
                if target == "executed":
                    action_message = f"已向{changed.payee_name}转账。"
                    summary = f"Simulated transfer to {changed.payee_name} executed."
                elif target == "scheduled":
                    action_message = f"已创建向{changed.payee_name}的定时转账。"
                    summary = f"Scheduled transfer to {changed.payee_name} created."
                else:
                    action_message = f"已取消向{changed.payee_name}的定时转账。"
                    summary = f"Scheduled transfer to {changed.payee_name} cancelled."
                return _complete_confirmed_resource(
                    session,
                    actor_id=actor_id,
                    task=task,
                    challenge=challenge,
                    execution=execution,
                    request_id=request_id,
                    resource_type="transfer",
                    resource_id=changed.id,
                    result_data=result_data,
                    result_summary=summary,
                    user_message=action_message,
                    before_state=before_state,
                    after_state=after_state,
                )

            if challenge.split_bill_id is not None:
                bill = session.scalar(
                    select(SplitBill).where(
                        SplitBill.id == challenge.split_bill_id, SplitBill.actor_id == actor_id
                    )
                )
                if bill is None:
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code="split_not_found",
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)
                target = challenge.target_status
                if target == "open":
                    participants = list(
                        session.scalars(
                            select(SplitParticipant)
                            .where(SplitParticipant.split_bill_id == bill.id)
                            .order_by(SplitParticipant.sequence)
                        )
                    )
                    normalized = {
                        "tool_name": challenge.tool_name,
                        "tool_version": challenge.tool_version,
                        "split_bill_id": str(bill.id),
                        "account_id": str(bill.account_id),
                        "title": bill.title,
                        "total_amount_minor": bill.total_amount_minor,
                        "participants": [item.display_name for item in participants[1:]],
                        "shares_minor": [item.amount_minor for item in participants],
                        "target_status": "open",
                    }
                    expected_tool = "transfer.split_create"
                else:
                    normalized = {
                        "tool_name": challenge.tool_name,
                        "tool_version": challenge.tool_version,
                        "split_bill_id": str(bill.id),
                        "target_status": "settled",
                        "split_bill_version": bill.version,
                    }
                    expected_tool = "transfer.split_collect"
                expected_state = "awaiting_confirmation" if target == "open" else "open"
                if (
                    bill.version != challenge.split_bill_version
                    or bill.status != expected_state
                    or _hash(normalized) != challenge.parameters_hash
                    or execution.input_hash != challenge.parameters_hash
                    or challenge.target_status not in {"open", "settled"}
                    or challenge.tool_name != expected_tool
                    or challenge.tool_version != TOOL_VERSION
                    or challenge.policy_version != "transfer-confirmation-v1"
                    or execution.idempotency_key != challenge.idempotency_key
                ):
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code="split_version_conflict",
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)
                before_state = {"status": bill.status, "version": bill.version}
                _transition(task, "running")
                execution.status = "running"
                challenge.status = "consumed"
                challenge.consumed_at = utc_now()
                try:
                    with session.begin_nested():
                        changed = confirm_split(
                            session,
                            actor_id=actor_id,
                            split_bill_id=bill.id,
                            target_status=target,
                            request_id=request_id,
                            task_id=task.id,
                            tool_execution_id=execution.id,
                        )
                except BankingRuleError as exc:
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code=exc.code,
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)
                after_state = {"status": changed.status, "version": changed.version}
                result_data = json.loads(
                    json.dumps(asdict(changed), ensure_ascii=False, default=str)
                )
                message = (
                    f"AA 分账“{changed.title}”已创建。"
                    if target == "open"
                    else f"AA 分账“{changed.title}”的模拟收款已完成。"
                )
                return _complete_confirmed_resource(
                    session,
                    actor_id=actor_id,
                    task=task,
                    challenge=challenge,
                    execution=execution,
                    request_id=request_id,
                    resource_type="split",
                    resource_id=changed.id,
                    result_data=result_data,
                    result_summary=message,
                    user_message=message,
                    before_state=before_state,
                    after_state=after_state,
                )

            if challenge.investment_order_id is not None:
                order = session.scalar(
                    select(InvestmentOrder).where(
                        InvestmentOrder.id == challenge.investment_order_id,
                        InvestmentOrder.actor_id == actor_id,
                    )
                )
                if order is None:
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code="investment_order_not_found",
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)
                product = session.get(InvestmentProduct, order.product_id)
                normalized = {
                    "tool_name": challenge.tool_name,
                    "tool_version": challenge.tool_version,
                    "order_id": str(order.id),
                    "order_type": order.order_type,
                    "account_id": str(order.account_id),
                    "product_id": str(order.product_id),
                    "holding_id": str(order.holding_id) if order.holding_id else None,
                    "amount_minor": order.amount_minor,
                    "units_micros": order.units_micros,
                    "unit_price_minor": product.unit_price_minor if product else None,
                    "target_status": "executed",
                }
                if (
                    order.version != challenge.investment_order_version
                    or order.status != "awaiting_confirmation"
                    or _hash(normalized) != challenge.parameters_hash
                    or execution.input_hash != challenge.parameters_hash
                    or challenge.target_status != "executed"
                    or challenge.tool_name != f"investment.{order.order_type}"
                    or challenge.tool_version != TOOL_VERSION
                    or challenge.policy_version != "investment-confirmation-v1"
                    or execution.idempotency_key != challenge.idempotency_key
                ):
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code="investment_order_version_conflict",
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)
                before_state = {"status": order.status, "version": order.version}
                _transition(task, "running")
                execution.status = "running"
                challenge.status = "consumed"
                challenge.consumed_at = utc_now()
                try:
                    with session.begin_nested():
                        changed = confirm_order(
                            session,
                            actor_id=actor_id,
                            order_id=order.id,
                            request_id=request_id,
                            task_id=task.id,
                            tool_execution_id=execution.id,
                        )
                except BankingRuleError as exc:
                    _mark_confirmation_rejected(
                        session,
                        task=task,
                        challenge=challenge,
                        execution=execution,
                        request_id=request_id,
                        error_code=exc.code,
                        outcome="rejected",
                    )
                    session.flush()
                    return _task_view(session, actor_id=actor_id, task_id=task.id)
                after_state = {"status": changed.status, "version": order.version}
                result_data = json.loads(
                    json.dumps(asdict(changed), ensure_ascii=False, default=str)
                )
                result_data["order"] = result_data.copy()
                action = "申购" if changed.order_type == "buy" else "赎回"
                message = f"{changed.product_name}已{action}。"
                return _complete_confirmed_resource(
                    session,
                    actor_id=actor_id,
                    task=task,
                    challenge=challenge,
                    execution=execution,
                    request_id=request_id,
                    resource_type="investment_order",
                    resource_id=changed.id,
                    result_data=result_data,
                    result_summary=message,
                    user_message=message,
                    before_state=before_state,
                    after_state=after_state,
                )

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
                "card": card_result_payload(changed),
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
        task.message = "任务已取消；尚未确认的操作没有执行。"
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
    "continue_confirmed_task",
    "confirm_card_change",
    "confirm_task_operation",
    "create_agent_task",
    "get_agent_task",
    "get_agent_task_by_idempotency_key",
    "get_recent_agent_task",
    "get_task_audit",
    "submit_task_input",
]
