"""Actor-scoped local support-ticket access, without banking authority."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from bankmate_api.api.errors import ContractHTTPException
from bankmate_api.application.handoffs import HandoffNotFoundError, get_handoff, request_handoff
from bankmate_api.infrastructure.database import get_db_session
from bankmate_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(prefix="/agent/tasks", tags=["agent"])


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal["user_requested", "partial_success", "cannot_continue"]


class HandoffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    task_id: UUID
    status: Literal["pending", "in_progress", "resolved"]
    reason: str
    outcome: str | None
    completed_tools: list[str]
    created_at: datetime
    updated_at: datetime


DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentActor = Annotated[DemoActor, Depends(get_current_demo_actor)]


@router.get("/{task_id}/handoff", response_model=HandoffResponse | None)
def read_handoff(
    task_id: UUID, session: DatabaseSession, actor: CurrentActor
) -> HandoffResponse | None:
    view = get_handoff(session, actor_id=actor.user_id, task_id=task_id)
    return HandoffResponse.model_validate(asdict(view)) if view else None


@router.post("/{task_id}/handoff", response_model=HandoffResponse)
def create_handoff(
    task_id: UUID,
    body: HandoffRequest,
    request: Request,
    session: DatabaseSession,
    actor: CurrentActor,
) -> HandoffResponse:
    try:
        view = request_handoff(
            session,
            actor_id=actor.user_id,
            task_id=task_id,
            reason=body.reason,
            request_id=request.state.request_id,
        )
    except HandoffNotFoundError:
        raise ContractHTTPException(404, "task_not_found", "没有找到这项任务。") from None
    return HandoffResponse.model_validate(asdict(view))
