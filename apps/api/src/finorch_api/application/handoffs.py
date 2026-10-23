"""Local simulated support tickets; never executes or reverses banking writes."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch_api.application.transactions import write_transaction
from finorch_api.infrastructure.models import (
    AgentTask,
    AuditEvent,
    HumanHandoff,
    ToolExecution,
    utc_now,
)


class HandoffNotFoundError(LookupError):
    pass


class HandoffStateError(ValueError):
    pass


@dataclass(frozen=True)
class HandoffView:
    id: UUID
    task_id: UUID
    status: str
    reason: str
    outcome: str | None
    completed_tools: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _view(session: Session, ticket: HumanHandoff) -> HandoffView:
    completed = session.scalars(
        select(ToolExecution.tool_name).where(
            ToolExecution.task_id == ticket.task_id,
            ToolExecution.actor_id == ticket.actor_id,
            ToolExecution.status == "succeeded",
        )
    )
    return HandoffView(
        ticket.id,
        ticket.task_id,
        ticket.status,
        ticket.reason,
        ticket.outcome,
        tuple(completed),
        _utc(ticket.created_at),
        _utc(ticket.updated_at),
    )


def get_handoff(session: Session, *, actor_id: UUID, task_id: UUID) -> HandoffView | None:
    ticket = session.scalar(
        select(HumanHandoff).where(
            HumanHandoff.actor_id == actor_id, HumanHandoff.task_id == task_id
        )
    )
    return _view(session, ticket) if ticket else None


def request_handoff(
    session: Session, *, actor_id: UUID, task_id: UUID, reason: str, request_id: str
) -> HandoffView:
    if reason not in {"user_requested", "partial_success", "cannot_continue"}:
        raise ValueError("Unsupported handoff reason.")
    with write_transaction(session, immediate=True):
        task = session.scalar(
            select(AgentTask).where(AgentTask.id == task_id, AgentTask.actor_id == actor_id)
        )
        if task is None:
            raise HandoffNotFoundError
        existing = get_handoff(session, actor_id=actor_id, task_id=task_id)
        if existing:
            return existing
        ticket = HumanHandoff(
            id=uuid4(),
            actor_id=actor_id,
            task_id=task_id,
            status="pending",
            reason=reason,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(ticket)
        session.flush()
        session.add(
            AuditEvent(
                actor_id=actor_id,
                task_id=task_id,
                event_type="handoff.requested",
                resource_type="human_handoff",
                resource_id=ticket.id,
                request_id=request_id,
                outcome="succeeded",
                after_state={"status": "pending", "reason": reason},
            )
        )
        session.flush()
        return _view(session, ticket)


def simulate_operator_update(
    session: Session, *, ticket_id: UUID, target_status: str, outcome: str | None, request_id: str
) -> HandoffView:
    """Only a local CLI may call this; no Agent Tool or HTTP write route exposes it."""
    if target_status not in {"in_progress", "resolved"}:
        raise HandoffStateError("Unsupported ticket status.")
    if target_status == "resolved" and not outcome:
        raise HandoffStateError("Resolution requires an outcome.")
    with write_transaction(session, immediate=True):
        ticket = session.get(HumanHandoff, ticket_id)
        if ticket is None:
            raise HandoffNotFoundError
        if (ticket.status, target_status) not in {
            ("pending", "in_progress"),
            ("in_progress", "resolved"),
        }:
            raise HandoffStateError("Invalid ticket transition.")
        before = ticket.status
        ticket.status = target_status
        ticket.outcome = outcome if target_status == "resolved" else None
        session.flush()
        session.add(
            AuditEvent(
                actor_id=ticket.actor_id,
                task_id=ticket.task_id,
                event_type="handoff.status_changed",
                resource_type="human_handoff",
                resource_id=ticket.id,
                request_id=request_id,
                outcome="succeeded",
                before_state={"status": before},
                after_state={"status": target_status, "outcome": ticket.outcome},
            )
        )
        session.flush()
        return _view(session, ticket)
