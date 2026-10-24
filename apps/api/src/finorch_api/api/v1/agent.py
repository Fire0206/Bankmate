from dataclasses import asdict
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request
from sqlalchemy.orm import Session

from finorch_api.agent.providers import ProviderSelection, select_provider
from finorch_api.api.errors import ContractHTTPException
from finorch_api.api.v1.agent_schemas import (
    AgentAuditResponse,
    AgentConfirmationRequest,
    AgentTaskCreateRequest,
    AgentTaskInputRequest,
    AgentTaskResponse,
)
from finorch_api.application.agent import (
    AgentIdempotencyConflictError,
    AgentTaskNotFoundError,
    AgentTaskStateConflictError,
    cancel_agent_task,
    continue_confirmed_task,
    create_agent_task,
    get_agent_task,
    get_agent_task_by_idempotency_key,
    get_recent_agent_task,
    get_task_audit,
    submit_task_input,
)
from finorch_api.application.agent import (
    confirm_task_operation as confirm_agent_task_operation,
)
from finorch_api.application.handoffs import create_failure_handoff_if_needed
from finorch_api.config import Settings, get_settings
from finorch_api.infrastructure.database import get_db_session
from finorch_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(prefix="/agent/tasks", tags=["agent"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentDemoActor = Annotated[DemoActor, Depends(get_current_demo_actor)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
RecoveryKey = Annotated[str, Path(min_length=1, max_length=128)]


def get_provider_selection(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProviderSelection:
    return select_provider(settings)


CurrentProviderSelection = Annotated[ProviderSelection, Depends(get_provider_selection)]


def _not_found() -> ContractHTTPException:
    return ContractHTTPException(404, "not_found", "Task not found.")


def _conflict(message: str, code: str = "conflict") -> ContractHTTPException:
    return ContractHTTPException(409, code, message)


def _task_response(value) -> AgentTaskResponse:
    return AgentTaskResponse.model_validate(asdict(value))


def _create_failure_handoff_if_needed(session: Session, *, actor_id: UUID, task, request_id: str):
    if task.status == "failed":
        create_failure_handoff_if_needed(
            session,
            actor_id=actor_id,
            task_id=task.id,
            request_id=request_id,
        )


@router.post("", response_model=AgentTaskResponse, summary="Submit a natural-language banking task")
def submit_task(
    body: AgentTaskCreateRequest,
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
    selection: CurrentProviderSelection,
    idempotency_key: IdempotencyKey,
) -> AgentTaskResponse:
    try:
        task = create_agent_task(
            session,
            actor_id=actor.user_id,
            request_text=body.request_text,
            conversation_id=body.conversation_id,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
            selection=selection,
        )
    except AgentIdempotencyConflictError:
        raise _conflict(
            "Idempotency key was already used for different input.", "idempotency_conflict"
        ) from None
    _create_failure_handoff_if_needed(
        session, actor_id=actor.user_id, task=task, request_id=request.state.request_id
    )
    return _task_response(task)


@router.get(
    "/recent",
    response_model=AgentTaskResponse | None,
    summary="Read the latest task for this actor and conversation",
)
def read_recent_task(
    conversation_id: UUID,
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> AgentTaskResponse | None:
    task = get_recent_agent_task(
        session,
        actor_id=actor.user_id,
        conversation_id=conversation_id,
        request_id=request.state.request_id,
    )
    return _task_response(task) if task is not None else None


@router.get(
    "/by-idempotency-key/{idempotency_key}",
    response_model=AgentTaskResponse | None,
    summary="Look up a task by an actor-scoped idempotency key",
)
def read_task_by_idempotency_key(
    idempotency_key: RecoveryKey,
    conversation_id: UUID,
    operation: Literal["create", "input", "confirm", "cancel"],
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
    task_id: UUID | None = None,
) -> AgentTaskResponse | None:
    if operation != "create" and task_id is None:
        raise ContractHTTPException(
            422,
            "validation_error",
            "Task ID is required for this idempotency lookup.",
        )
    task = get_agent_task_by_idempotency_key(
        session,
        actor_id=actor.user_id,
        conversation_id=conversation_id,
        idempotency_key=idempotency_key,
        operation=operation,
        task_id=task_id,
        request_id=request.state.request_id,
    )
    return _task_response(task) if task is not None else None


@router.get("/{task_id}", response_model=AgentTaskResponse, summary="Read task state and steps")
def read_task(
    task_id: UUID,
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> AgentTaskResponse:
    try:
        return _task_response(
            get_agent_task(
                session,
                actor_id=actor.user_id,
                task_id=task_id,
                request_id=request.state.request_id,
            )
        )
    except AgentTaskNotFoundError:
        raise _not_found() from None


@router.post(
    "/{task_id}/input",
    response_model=AgentTaskResponse,
    summary="Provide or revise task input",
)
def provide_task_input(
    task_id: UUID,
    body: AgentTaskInputRequest,
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
    selection: CurrentProviderSelection,
    idempotency_key: IdempotencyKey,
) -> AgentTaskResponse:
    try:
        task = submit_task_input(
            session,
            actor_id=actor.user_id,
            task_id=task_id,
            request_text=body.request_text,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
            selection=selection,
        )
    except AgentTaskNotFoundError:
        raise _not_found() from None
    except AgentIdempotencyConflictError:
        raise _conflict(
            "Idempotency key was already used for different input.", "idempotency_conflict"
        ) from None
    except AgentTaskStateConflictError:
        raise _conflict(
            "Task is not waiting for user input or confirmation.", "task_state_conflict"
        ) from None
    _create_failure_handoff_if_needed(
        session, actor_id=actor.user_id, task=task, request_id=request.state.request_id
    )
    return _task_response(task)


@router.post(
    "/{task_id}/confirm",
    response_model=AgentTaskResponse,
    summary="Confirm a server-created banking operation challenge",
)
def confirm_task_operation(
    task_id: UUID,
    body: AgentConfirmationRequest,
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
    selection: CurrentProviderSelection,
    idempotency_key: IdempotencyKey,
) -> AgentTaskResponse:
    try:
        task = confirm_agent_task_operation(
            session,
            actor_id=actor.user_id,
            task_id=task_id,
            challenge_id=body.challenge_id,
            parameters_hash=body.parameters_hash,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
            verification_code=body.verification_code,
        )
    except AgentTaskNotFoundError:
        raise _not_found() from None
    except AgentIdempotencyConflictError:
        raise _conflict(
            "Idempotency key or confirmation parameters conflict.", "idempotency_conflict"
        ) from None
    except AgentTaskStateConflictError:
        raise _conflict("Confirmation is no longer pending.", "confirmation_not_pending") from None
    if task.status == "running":
        task = continue_confirmed_task(
            session,
            actor_id=actor.user_id,
            task_id=task_id,
            request_id=request.state.request_id,
            selection=selection,
        )
    _create_failure_handoff_if_needed(
        session, actor_id=actor.user_id, task=task, request_id=request.state.request_id
    )
    if task.error_code == "confirmation_parameters_mismatch":
        raise _conflict(
            "Confirmation details changed; the challenge was invalidated.",
            "confirmation_invalidated",
        )
    if task.error_code == "confirmation_expired":
        raise _conflict("Confirmation expired; no business state changed.", "confirmation_expired")
    if task.error_code == "safety_hold_active":
        raise _conflict(
            "A temporary demo safety hold blocks write operations; read access remains available.",
            "safety_hold_active",
        )
    if task.error_code in {
        "strong_verification_required",
        "verification_unavailable",
        "verification_expired",
        "verification_invalidated",
        "verification_incorrect",
        "verification_locked",
    }:
        raise _conflict("Simulated second verification was not accepted.", task.error_code)
    if task.error_code in {
        "card_version_conflict",
        "card_application_version_conflict",
        "card_application_exists",
        "subscription_version_conflict",
        "transfer_version_conflict",
        "transfer_state_conflict",
        "split_version_conflict",
        "split_state_conflict",
        "investment_order_conflict",
        "holding_version_conflict",
        "insufficient_funds",
        "risk_mismatch",
    }:
        raise _conflict(
            "The item changed after this confirmation was created.",
            task.error_code,
        )
    return _task_response(task)


@router.post("/{task_id}/cancel", response_model=AgentTaskResponse, summary="Cancel a pending task")
def cancel_task(
    task_id: UUID,
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
    idempotency_key: IdempotencyKey,
) -> AgentTaskResponse:
    try:
        task = cancel_agent_task(
            session,
            actor_id=actor.user_id,
            task_id=task_id,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
    except AgentTaskNotFoundError:
        raise _not_found() from None
    except AgentIdempotencyConflictError:
        raise _conflict(
            "Idempotency key was already used for a different task operation.",
            "idempotency_conflict",
        ) from None
    except AgentTaskStateConflictError:
        raise _conflict("Task is already in a terminal state.", "task_state_conflict") from None
    return _task_response(task)


@router.get(
    "/{task_id}/audit", response_model=AgentAuditResponse, summary="Read task audit summary"
)
def read_task_audit(
    task_id: UUID,
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> AgentAuditResponse:
    try:
        events = get_task_audit(session, actor_id=actor.user_id, task_id=task_id)
    except AgentTaskNotFoundError:
        raise _not_found() from None
    return AgentAuditResponse(task_id=task_id, events=[asdict(event) for event in events])
