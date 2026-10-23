"""Local demo OTP service; no LLM tool can issue or retrieve verification codes."""

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch_api.infrastructure.models import (
    AuditEvent,
    ConfirmationChallenge,
    InvestmentOrder,
    InvestmentProduct,
    StrongVerification,
    Transfer,
)
from finorch_api.security.risk_policy import (
    RiskDecision,
    business_day_bounds,
    decide_risk,
    executed_transfer_total,
)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def challenge_risk(
    session: Session, challenge: ConfirmationChallenge, now: datetime
) -> RiskDecision:
    if challenge.tool_name in {"card.report_lost", "card.replace"}:
        return decide_risk(operation="sensitive_card")
    if challenge.transfer_id and challenge.target_status != "cancelled":
        transfer = session.get(Transfer, challenge.transfer_id)
        if transfer is None or transfer.actor_id != challenge.actor_id:
            raise ValueError("Invalid transfer ownership.")
        return decide_risk(
            operation="transfer",
            amount_minor=transfer.amount_minor,
            currency=transfer.currency,
            daily_executed_minor=executed_transfer_total(
                session, actor_id=challenge.actor_id, now=now
            ),
        )
    if challenge.investment_order_id:
        order = session.get(InvestmentOrder, challenge.investment_order_id)
        if order is None or order.actor_id != challenge.actor_id:
            raise ValueError("Invalid investment ownership.")
        if order.order_type == "buy":
            product = session.get(InvestmentProduct, order.product_id)
            return decide_risk(
                operation="investment_buy", product_risk=product.risk_level if product else None
            )
    return decide_risk(operation="write")


def binding(challenge: ConfirmationChallenge, decision: RiskDecision, now: datetime) -> str:
    payload = {
        "actor": str(challenge.actor_id),
        "task": str(challenge.task_id),
        "confirmation": str(challenge.id),
        "parameters": challenge.parameters_hash,
        "tool": challenge.tool_name,
        "tool_version": challenge.tool_version,
        "target": challenge.target_status,
        "policy": decision.policy_version,
        "risk": decision.level,
        "rules": decision.rules,
        "day": business_day_bounds(now)[0].isoformat(),
        "expires": aware(challenge.expires_at).isoformat(),
        "versions": [
            challenge.card_version,
            challenge.subscription_version,
            challenge.transfer_version,
            challenge.split_bill_version,
            challenge.investment_order_version,
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def code_digest(code: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), 100_000).hex()


def issue_demo_code(
    session: Session,
    *,
    actor_id: UUID,
    confirmation_id: UUID,
    now: datetime,
) -> tuple[StrongVerification, str]:
    """Caller owns serialized UoW. Deliver returned code only through local CLI."""
    challenge = session.get(ConfirmationChallenge, confirmation_id)
    if challenge is None or challenge.actor_id != actor_id:
        raise ValueError("Confirmation not found.")
    if challenge.status != "pending" or aware(challenge.expires_at) <= now:
        raise ValueError("Confirmation is not pending.")
    decision = challenge_risk(session, challenge, now)
    if decision.level != "red":
        raise ValueError("This operation does not require strong verification.")
    existing = session.scalar(
        select(StrongVerification).where(StrongVerification.confirmation_id == confirmation_id)
    )
    if existing is not None:
        raise ValueError("A code was already issued; cancel and create a new proposal to restart.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(32)
    verification = StrongVerification(
        id=uuid4(),
        confirmation_id=confirmation_id,
        actor_id=actor_id,
        binding_hash=binding(challenge, decision, now),
        code_hash=code_digest(code, salt),
        salt=salt,
        attempts=0,
        status="pending",
        expires_at=min(aware(challenge.expires_at), now + timedelta(minutes=3)),
        created_at=now,
    )
    session.add(verification)
    session.add(
        AuditEvent(
            actor_id=actor_id,
            event_type="security.verification_issued",
            resource_type="confirmation",
            resource_id=confirmation_id,
            request_id="local-demo-verification",
            task_id=challenge.task_id,
            tool_execution_id=challenge.tool_execution_id,
            outcome="issued",
            after_state={
                "risk_level": decision.level,
                "method": decision.confirmation_method,
                "policy_version": decision.policy_version,
                "expires_at": verification.expires_at.isoformat(),
            },
        )
    )
    session.flush()
    return verification, code


def consume_demo_code(
    session: Session,
    *,
    challenge: ConfirmationChallenge,
    decision: RiskDecision,
    code: str | None,
    now: datetime,
) -> str | None:
    """Return an error code, retaining attempt changes in the caller's transaction.

    Success consumes once; rollback of the encompassing business transaction also
    rolls back consumption. This function must never commit independently.
    """
    record = session.scalar(
        select(StrongVerification).where(
            StrongVerification.confirmation_id == challenge.id,
            StrongVerification.actor_id == challenge.actor_id,
        )
    )
    if record is None or code is None:
        return "strong_verification_required"
    if record.status != "pending":
        return "verification_unavailable"
    if aware(record.expires_at) <= now:
        record.status = "expired"
        return "verification_expired"
    if record.binding_hash != binding(challenge, decision, now):
        record.status = "invalidated"
        return "verification_invalidated"
    record.attempts += 1
    if not hmac.compare_digest(record.code_hash, code_digest(code, record.salt)):
        if record.attempts >= 5:
            record.status = "locked"
        return "verification_locked" if record.status == "locked" else "verification_incorrect"
    record.status = "consumed"
    return None
