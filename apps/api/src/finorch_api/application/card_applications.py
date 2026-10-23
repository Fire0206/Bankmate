"""Synthetic debit-card requests and explicit local demo review."""

from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import randbelow
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch_api.agent.context import ToolCallContext
from finorch_api.application.confirmation import create_confirmation_challenge, parameters_hash
from finorch_api.application.errors import BankingRuleError
from finorch_api.application.transactions import write_transaction
from finorch_api.domain.cards import CardStatus
from finorch_api.infrastructure.models import (
    Account,
    AuditEvent,
    Card,
    CardApplication,
    utc_now,
)

POLICY_VERSION = "card-application-v1"
TOOL_VERSION = "1.0"


@dataclass(frozen=True)
class CardApplicationView:
    id: UUID
    account_id: UUID
    account_label: str
    label: str
    status: str
    issued_card_id: UUID | None
    issued_card_suffix: str | None
    version: int
    created_at: datetime
    reviewed_at: datetime | None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _view(session: Session, row: CardApplication) -> CardApplicationView:
    account = session.get(Account, row.account_id)
    issued = session.get(Card, row.issued_card_id) if row.issued_card_id else None
    return CardApplicationView(
        id=row.id,
        account_id=row.account_id,
        account_label=account.label if account else "模拟账户",
        label=row.label,
        status=row.status,
        issued_card_id=row.issued_card_id,
        issued_card_suffix=issued.card_suffix if issued else None,
        version=row.version,
        created_at=_utc(row.created_at),
        reviewed_at=_utc(row.reviewed_at),
    )


def list_card_applications(session: Session, *, actor_id: UUID) -> tuple[CardApplicationView, ...]:
    rows = session.scalars(
        select(CardApplication)
        .where(
            CardApplication.actor_id == actor_id,
            CardApplication.status.in_(("submitted", "approved", "rejected")),
        )
        .order_by(CardApplication.created_at.desc(), CardApplication.id.desc())
        .limit(100)
    )
    return tuple(_view(session, row) for row in rows)


def propose_card_application(
    session: Session,
    *,
    context: ToolCallContext,
    account_label: str | None,
    card_label: str,
) -> dict[str, object]:
    label = card_label.strip()
    if not label or len(label) > 80:
        raise BankingRuleError("invalid_card_label", "卡片名称须为 1 至 80 个字符。")
    statement = select(Account).where(Account.demo_user_id == context.actor_id)
    if account_label:
        statement = statement.where(Account.label == account_label.strip())
    accounts = list(session.scalars(statement.order_by(Account.created_at, Account.id).limit(2)))
    if not accounts:
        raise BankingRuleError("account_not_found", "没有找到当前用户的指定模拟账户。")
    if account_label is None and len(accounts) > 1:
        raise BankingRuleError("account_ambiguous", "请指定要绑定的模拟账户。")
    account = accounts[0]
    if session.scalar(
        select(CardApplication.id).where(
            CardApplication.actor_id == context.actor_id,
            CardApplication.account_id == account.id,
            CardApplication.status == "submitted",
        )
    ):
        raise BankingRuleError("card_application_exists", "这个账户已有待模拟审核的借记卡申请。")
    row = CardApplication(
        id=uuid4(),
        actor_id=context.actor_id,
        account_id=account.id,
        label=label,
        status="pending_confirmation",
        version=1,
    )
    session.add(row)
    session.flush()
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "application_id": str(row.id),
        "account_id": str(account.id),
        "label": row.label,
        "target_status": "submitted",
    }
    digest = parameters_hash(normalized)
    context.execution.input_hash = digest
    challenge = create_confirmation_challenge(
        session,
        actor_id=context.actor_id,
        task_id=context.task.id,
        tool_execution_id=context.execution.id,
        tool_name=context.execution.tool_name,
        tool_version=context.execution.tool_version,
        idempotency_key=context.execution.idempotency_key,
        policy_version=POLICY_VERSION,
        parameters_digest=digest,
        target_status="submitted",
        resource_type="card_application",
        resource_id=row.id,
        resource_version=row.version,
    )
    return {
        "status": "awaiting_confirmation",
        "confirmation_required": True,
        "challenge_id": challenge.id,
        "application_id": row.id,
        "account_id": account.id,
        "account_label": account.label,
        "card_label": row.label,
        "current_status": row.status,
        "target_status": "submitted",
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "card_application",
        "resource_id": row.id,
        "resource_label": row.label,
        "resource_version": row.version,
    }


def submit_card_application(
    session: Session,
    *,
    actor_id: UUID,
    application_id: UUID,
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID,
) -> CardApplicationView:
    with write_transaction(session):
        row = session.scalar(
            select(CardApplication).where(
                CardApplication.id == application_id, CardApplication.actor_id == actor_id
            )
        )
        if row is None:
            raise BankingRuleError("card_application_not_found", "没有找到这份模拟卡申请。")
        if row.status != "pending_confirmation":
            raise BankingRuleError("card_application_state_conflict", "申请状态已变化。")
        if session.scalar(
            select(CardApplication.id).where(
                CardApplication.actor_id == actor_id,
                CardApplication.account_id == row.account_id,
                CardApplication.status == "submitted",
                CardApplication.id != row.id,
            )
        ):
            raise BankingRuleError(
                "card_application_exists", "这个账户已有待模拟审核的借记卡申请。"
            )
        row.status = "submitted"
        session.flush()
        session.add(
            AuditEvent(
                actor_id=actor_id,
                event_type="card.application_submitted",
                resource_type="card_application",
                resource_id=row.id,
                request_id=request_id,
                task_id=task_id,
                tool_execution_id=tool_execution_id,
                outcome="succeeded",
                before_state={"status": "pending_confirmation"},
                after_state={"status": "submitted"},
            )
        )
        session.flush()
        return _view(session, row)


def review_card_application(
    session: Session, *, application_id: UUID, approve: bool
) -> CardApplicationView:
    """Local operator only; never exposed as an Agent tool or public API."""
    with write_transaction(session, immediate=True):
        row = session.get(CardApplication, application_id)
        if row is None or row.status != "submitted":
            raise BankingRuleError("card_application_state_conflict", "仅可审核已提交的模拟申请。")
        if approve:
            suffixes = set(
                session.scalars(
                    select(Card.card_suffix)
                    .join(Account, Card.account_id == Account.id)
                    .where(Account.demo_user_id == row.actor_id)
                )
            )
            suffix = next(
                (
                    candidate
                    for _ in range(100)
                    if (candidate := f"{randbelow(10000):04d}") not in suffixes
                ),
                None,
            )
            if suffix is None:
                raise BankingRuleError("card_suffix_unavailable", "模拟卡尾号暂不可用。")
            card = Card(
                id=uuid4(),
                account_id=row.account_id,
                label=row.label,
                card_suffix=suffix,
                status=CardStatus.ACTIVE,
            )
            session.add(card)
            session.flush()
            row.issued_card_id = card.id
        row.status = "approved" if approve else "rejected"
        row.reviewed_at = utc_now()
        session.flush()
        session.add(
            AuditEvent(
                actor_id=row.actor_id,
                card_id=row.issued_card_id,
                event_type="card.application_reviewed",
                resource_type="card_application",
                resource_id=row.id,
                request_id="local-demo-review",
                outcome=row.status,
                before_state={"status": "submitted"},
                after_state={
                    "status": row.status,
                    "issued_card_id": str(row.issued_card_id) if row.issued_card_id else None,
                },
            )
        )
        session.flush()
        return _view(session, row)
