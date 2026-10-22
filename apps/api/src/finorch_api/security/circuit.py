"""Short-lived, actor-scoped demo write hold derived from append-only audit events."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch_api.infrastructure.models import AuditEvent, utc_now

SIGNAL_WINDOW = timedelta(minutes=5)
HOLD_DURATION = timedelta(minutes=2)
SIGNAL_THRESHOLD = 3

_PARAMETER_ERRORS = {"tool_input_invalid", "unknown_tool", "repeated_tool_call"}
_OWNERSHIP_ERRORS = {
    "card_not_found",
    "subscription_not_found",
    "payee_not_found",
    "transfer_not_found",
    "investment_order_not_found",
}
_PROVIDER_ERRORS = {
    "llm_provider_timeout",
    "llm_provider_invalid_response",
    "llm_provider_http_error",
    "llm_provider_unavailable",
    "agent_runtime_error",
}
_VERIFICATION_ERRORS = {
    "verification_incorrect",
    "verification_locked",
    "verification_invalidated",
}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def signal_category(code: str) -> str | None:
    if code in _PARAMETER_ERRORS:
        return "invalid_tool_input"
    if code in _OWNERSHIP_ERRORS:
        return "resource_access"
    if code in _PROVIDER_ERRORS:
        return "provider_failure"
    if code in _VERIFICATION_ERRORS:
        return "verification_failure"
    return None


def active_write_hold(
    session: Session, *, actor_id: UUID, now: datetime | None = None
) -> datetime | None:
    now = now or utc_now()
    latest = session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.actor_id == actor_id,
            AuditEvent.event_type == "security.write_hold_started",
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    if latest is None or not latest.after_state:
        return None
    expires = latest.after_state.get("expires_at")
    if not isinstance(expires, str):
        return None
    deadline = _aware(datetime.fromisoformat(expires))
    return deadline if deadline > now else None


def record_safety_signal(
    session: Session,
    *,
    actor_id: UUID,
    code: str,
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """Caller owns a serialized write transaction. Never stores raw model input."""
    category = signal_category(code)
    if category is None:
        return None
    now = now or utc_now()
    session.add(
        AuditEvent(
            actor_id=actor_id,
            event_type="security.risk_signal",
            resource_type="task",
            resource_id=task_id,
            request_id=request_id,
            task_id=task_id,
            tool_execution_id=tool_execution_id,
            outcome="blocked",
            after_state={"category": category, "error_code": code},
            occurred_at=now,
        )
    )
    session.flush()
    if active_write_hold(session, actor_id=actor_id, now=now) is not None:
        return None
    recent = session.scalars(
        select(AuditEvent).where(
            AuditEvent.actor_id == actor_id,
            AuditEvent.event_type == "security.risk_signal",
            AuditEvent.occurred_at >= now - SIGNAL_WINDOW,
        )
    )
    count = sum(
        1 for event in recent if event.after_state and event.after_state.get("category") == category
    )
    if count < SIGNAL_THRESHOLD:
        return None
    deadline = now + HOLD_DURATION
    session.add(
        AuditEvent(
            actor_id=actor_id,
            event_type="security.write_hold_started",
            resource_type="demo_user",
            resource_id=actor_id,
            request_id=request_id,
            task_id=task_id,
            tool_execution_id=tool_execution_id,
            outcome="blocked",
            after_state={
                "category": category,
                "expires_at": deadline.isoformat(),
                "scope": "write_operations",
            },
            occurred_at=now,
        )
    )
    return deadline
