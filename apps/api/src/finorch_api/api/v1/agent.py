from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
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
    confirm_card_change,
    create_agent_task,
    get_agent_task,
    get_task_audit,
    submit_task_input,
)
from finorch_api.config import Settings, get_settings
from finorch_api.infrastructure.database import get_db_session
from finorch_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(prefix="/agent/tasks", tags=["agent"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentDemoActor = Annotated[DemoActor, Depends(get_current_demo_actor)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


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


@router.post("", response_model=AgentTaskResponse, summary="Submit a natural-language card task")
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
    return _task_response(task)


@router.get("/{task_id}", response_model=AgentTaskResponse, summary="Read task state and steps")
def read_task(
    task_id: UUID,
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> AgentTaskResponse:
    try:
        return _task_response(get_agent_task(session, actor_id=actor.user_id, task_id=task_id))
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
    return _task_response(task)


@router.post(
    "/{task_id}/confirm",
    response_model=AgentTaskResponse,
    summary="Confirm a server-created card operation challenge",
)
def confirm_task_operation(
    task_id: UUID,
    body: AgentConfirmationRequest,
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
    idempotency_key: IdempotencyKey,
) -> AgentTaskResponse:
    try:
        task = confirm_card_change(
            session,
            actor_id=actor.user_id,
            task_id=task_id,
            challenge_id=body.challenge_id,
            parameters_hash=body.parameters_hash,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
    except AgentTaskNotFoundError:
        raise _not_found() from None
    except AgentIdempotencyConflictError:
        raise _conflict(
            "Idempotency key or confirmation parameters conflict.", "idempotency_conflict"
        ) from None
    except AgentTaskStateConflictError:
        raise _conflict("Confirmation is no longer pending.", "confirmation_not_pending") from None
    if task.error_code == "confirmation_parameters_mismatch":
        raise _conflict(
            "Confirmation parameters changed; the challenge was invalidated.",
            "confirmation_invalidated",
        )
    if task.error_code == "confirmation_expired":
        raise _conflict("Confirmation expired; no card change was made.", "confirmation_expired")
    if task.error_code == "card_version_conflict":
        raise _conflict("Card changed after this challenge was created.", "card_version_conflict")
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
