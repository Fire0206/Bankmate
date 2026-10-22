from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from finorch_api.agent.context import ToolCallContext
from finorch_api.application.confirmation import create_confirmation_challenge, parameters_hash
from finorch_api.application.errors import BankingRuleError
from finorch_api.application.transactions import write_transaction
from finorch_api.domain.transfers import split_amount
from finorch_api.infrastructure.models import (
    Account,
    AuditEvent,
    DemoUser,
    Payee,
    SplitBill,
    SplitParticipant,
    Transaction,
    Transfer,
    utc_now,
)
from finorch_api.security.risk_policy import decide_risk, executed_transfer_total

POLICY_VERSION = "transfer-confirmation-v1"
TOOL_VERSION = "1.0"


@dataclass(frozen=True)
class AccountBalanceView:
    id: UUID
    label: str
    currency: str
    balance_minor: int


@dataclass(frozen=True)
class PayeeView:
    id: UUID
    display_name: str
    destination_account_id: UUID
    destination_account_label: str
    currency: str


@dataclass(frozen=True)
class TransferView:
    id: UUID
    source_account_id: UUID
    source_account_label: str
    destination_account_id: UUID
    payee_name: str
    amount_minor: int
    currency: str
    transfer_type: str
    status: str
    scheduled_at: datetime | None
    executed_at: datetime | None
    version: int


@dataclass(frozen=True)
class SplitParticipantView:
    id: UUID
    display_name: str
    amount_minor: int
    status: str


@dataclass(frozen=True)
class SplitBillView:
    id: UUID
    title: str
    total_amount_minor: int
    currency: str
    participant_count: int
    status: str
    participants: tuple[SplitParticipantView, ...]
    version: int


def _normal_name(value: str) -> str:
    return "".join(value.split()).casefold()


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def list_accounts(session: Session, *, actor_id: UUID) -> tuple[AccountBalanceView, ...]:
    rows = session.scalars(
        select(Account)
        .where(Account.demo_user_id == actor_id)
        .order_by(Account.created_at, Account.id)
    )
    return tuple(
        AccountBalanceView(row.id, row.label, row.currency, row.balance_minor) for row in rows
    )


def _owned_account(session: Session, *, actor_id: UUID, label: str | None = None) -> Account:
    statement = select(Account).where(Account.demo_user_id == actor_id)
    if label:
        statement = statement.where(Account.label.ilike(label.strip()))
    account = session.scalar(statement.order_by(Account.created_at, Account.id).limit(1))
    if account is None:
        raise BankingRuleError("account_not_found", "没有找到当前模拟用户的指定账户。")
    return account


def list_payees(session: Session, *, actor_id: UUID) -> tuple[PayeeView, ...]:
    rows = session.execute(
        select(Payee, Account)
        .join(Account, Account.id == Payee.destination_account_id)
        .where(Payee.actor_id == actor_id)
        .order_by(Payee.normalized_name)
    )
    return tuple(
        PayeeView(payee.id, payee.display_name, account.id, account.label, account.currency)
        for payee, account in rows
    )


def create_payee(
    session: Session,
    *,
    actor_id: UUID,
    display_name: str,
    destination_account_id: UUID,
) -> PayeeView:
    name = display_name.strip()
    normalized = _normal_name(name)
    if not normalized or len(name) > 80:
        raise BankingRuleError("invalid_payee", "收款人名称不能为空且不能超过 80 个字符。")
    with write_transaction(session, immediate=True):
        duplicate = session.scalar(
            select(Payee).where(Payee.actor_id == actor_id, Payee.normalized_name == normalized)
        )
        if duplicate is not None:
            raise BankingRuleError("payee_exists", "这个收款人名称已存在。")
        account = session.get(Account, destination_account_id)
        if account is None:
            raise BankingRuleError("destination_not_found", "没有找到指定的模拟收款账户。")
        payee = Payee(
            id=uuid4(),
            actor_id=actor_id,
            destination_account_id=account.id,
            display_name=name,
            normalized_name=normalized,
        )
        session.add(payee)
        session.flush()
        return PayeeView(payee.id, payee.display_name, account.id, account.label, account.currency)


def delete_payee(session: Session, *, actor_id: UUID, payee_id: UUID) -> None:
    with write_transaction(session, immediate=True):
        payee = session.scalar(
            select(Payee).where(Payee.id == payee_id, Payee.actor_id == actor_id)
        )
        if payee is None:
            raise BankingRuleError("payee_not_found", "没有找到当前模拟用户的这位收款人。")
        if session.scalar(select(Transfer.id).where(Transfer.payee_id == payee.id).limit(1)):
            raise BankingRuleError("payee_in_use", "已有转账记录使用这位收款人，暂时不能删除。")
        session.delete(payee)


def _transfer_view(session: Session, transfer: Transfer) -> TransferView:
    source = session.get(Account, transfer.source_account_id)
    return TransferView(
        id=transfer.id,
        source_account_id=transfer.source_account_id,
        source_account_label=source.label if source else "模拟账户",
        destination_account_id=transfer.destination_account_id,
        payee_name=transfer.payee_name,
        amount_minor=transfer.amount_minor,
        currency=transfer.currency,
        transfer_type=transfer.transfer_type,
        status=transfer.status,
        scheduled_at=_utc(transfer.scheduled_at),
        executed_at=_utc(transfer.executed_at),
        version=transfer.version,
    )


def list_transfers(
    session: Session, *, actor_id: UUID, limit: int = 50
) -> tuple[TransferView, ...]:
    rows = session.scalars(
        select(Transfer)
        .where(Transfer.actor_id == actor_id)
        .order_by(Transfer.created_at.desc(), Transfer.id)
        .limit(limit)
    )
    return tuple(_transfer_view(session, row) for row in rows)


def get_transfer(session: Session, *, actor_id: UUID, transfer_id: UUID) -> TransferView | None:
    row = session.scalar(
        select(Transfer).where(Transfer.id == transfer_id, Transfer.actor_id == actor_id)
    )
    return _transfer_view(session, row) if row else None


def _payee_by_name(session: Session, *, actor_id: UUID, name: str) -> Payee:
    normalized = _normal_name(name)
    rows = list(
        session.scalars(
            select(Payee).where(Payee.actor_id == actor_id, Payee.normalized_name == normalized)
        )
    )
    if not rows:
        raise BankingRuleError("payee_not_found", "没有找到这个收款人，请先添加收款人。")
    if len(rows) > 1:
        raise BankingRuleError("ambiguous_payee", "收款人名称不唯一，请提供更具体的名称。")
    return rows[0]


def propose_transfer(
    session: Session,
    *,
    context: ToolCallContext,
    payee_name: str,
    amount_minor: int,
    currency: str = "CNY",
    source_account_label: str | None = None,
    scheduled_at: datetime | None = None,
) -> dict[str, object]:
    if amount_minor <= 0:
        raise BankingRuleError("invalid_amount", "转账金额必须大于零。")
    account = _owned_account(session, actor_id=context.actor_id, label=source_account_label)
    payee = _payee_by_name(session, actor_id=context.actor_id, name=payee_name)
    destination = session.get(Account, payee.destination_account_id)
    if destination is None or account.id == destination.id:
        raise BankingRuleError("invalid_destination", "收款账户无效，或不能转给同一账户。")
    if currency != account.currency or currency != destination.currency:
        raise BankingRuleError("currency_mismatch", "转出和收款账户的币种必须相同。")
    if account.balance_minor < amount_minor:
        raise BankingRuleError("insufficient_funds", "账户余额不足，未创建转账。")
    if scheduled_at is not None:
        scheduled_at = _utc(scheduled_at)
        now = utc_now()
        if scheduled_at is None or scheduled_at <= now:
            raise BankingRuleError("invalid_schedule_time", "定时转账时间必须晚于当前时间。")
        if scheduled_at > now + timedelta(days=365):
            raise BankingRuleError("invalid_schedule_time", "定时转账不能超过一年。")
    transfer_type = "scheduled" if scheduled_at is not None else "immediate"
    transfer = Transfer(
        id=uuid4(),
        actor_id=context.actor_id,
        source_account_id=account.id,
        destination_account_id=destination.id,
        payee_id=payee.id,
        payee_name=payee.display_name,
        amount_minor=amount_minor,
        currency=currency,
        transfer_type=transfer_type,
        status="awaiting_confirmation",
        scheduled_at=scheduled_at,
        idempotency_key=context.execution.idempotency_key,
        version=1,
    )
    session.add(transfer)
    session.flush()
    target = "scheduled" if scheduled_at else "executed"
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "transfer_id": str(transfer.id),
        "source_account_id": str(account.id),
        "destination_account_id": str(destination.id),
        "payee_id": str(payee.id),
        "amount_minor": amount_minor,
        "currency": currency,
        "transfer_type": transfer_type,
        "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
        "target_status": target,
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
        target_status=target,
        resource_type="transfer",
        resource_id=transfer.id,
        resource_version=transfer.version,
    )
    return {
        "status": "awaiting_confirmation",
        "confirmation_required": True,
        "challenge_id": challenge.id,
        "transfer_id": transfer.id,
        "source_account_label": account.label,
        "payee_name": payee.display_name,
        "amount_minor": amount_minor,
        "currency": currency,
        "transfer_type": transfer_type,
        "scheduled_at": scheduled_at,
        "current_status": "pending_confirmation",
        "target_status": target,
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "transfer",
        "resource_id": transfer.id,
        "resource_label": payee.display_name,
        "resource_version": transfer.version,
    }


def propose_cancel_scheduled(
    session: Session,
    *,
    context: ToolCallContext,
    transfer_id: UUID | None = None,
    payee_name: str | None = None,
) -> dict[str, object]:
    statement = select(Transfer).where(
        Transfer.actor_id == context.actor_id,
        Transfer.transfer_type == "scheduled",
        Transfer.status == "scheduled",
    )
    if transfer_id is not None:
        statement = statement.where(Transfer.id == transfer_id)
    elif payee_name:
        statement = statement.where(Transfer.payee_name.ilike(payee_name.strip()))
    else:
        raise BankingRuleError("transfer_target_required", "请说明要取消的收款人或转账记录。")
    transfer = session.scalar(statement.order_by(Transfer.created_at.desc()).limit(1))
    if transfer is None:
        raise BankingRuleError("transfer_not_found", "没有找到当前用户的这笔定时转账。")
    if transfer.transfer_type != "scheduled" or transfer.status != "scheduled":
        raise BankingRuleError("transfer_not_cancellable", "这笔转账当前不能取消。")
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "transfer_id": str(transfer.id),
        "target_status": "cancelled",
        "transfer_version": transfer.version,
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
        target_status="cancelled",
        resource_type="transfer",
        resource_id=transfer.id,
        resource_version=transfer.version,
    )
    return {
        "status": "awaiting_confirmation",
        "confirmation_required": True,
        "challenge_id": challenge.id,
        "transfer_id": transfer.id,
        "payee_name": transfer.payee_name,
        "amount_minor": transfer.amount_minor,
        "currency": transfer.currency,
        "transfer_type": transfer.transfer_type,
        "scheduled_at": _utc(transfer.scheduled_at),
        "current_status": transfer.status,
        "target_status": "cancelled",
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "transfer",
        "resource_id": transfer.id,
        "resource_label": transfer.payee_name,
        "resource_version": transfer.version,
    }


def _account_delta(session: Session, *, account_id: UUID, amount_minor: int) -> bool:
    account = session.get(Account, account_id)
    result = session.execute(
        update(Account)
        .where(Account.id == account_id, Account.balance_minor >= -amount_minor)
        .values(
            balance_minor=Account.balance_minor + amount_minor,
            version=Account.version + 1,
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 1 and account is not None:
        session.expire(account, ["balance_minor", "version", "updated_at"])
    return result.rowcount == 1


def _execute_money_transfer(
    session: Session,
    *,
    transfer: Transfer,
    request_id: str,
    task_id: UUID | None,
    tool_execution_id: UUID | None,
) -> None:
    source = session.get(Account, transfer.source_account_id)
    destination = session.get(Account, transfer.destination_account_id)
    payee = session.get(Payee, transfer.payee_id)
    if (
        source is None
        or destination is None
        or payee is None
        or payee.actor_id != transfer.actor_id
        or payee.destination_account_id != destination.id
        or source.demo_user_id != transfer.actor_id
        or source.currency != transfer.currency
        or destination.currency != transfer.currency
    ):
        raise BankingRuleError("transfer_integrity_error", "转账账户或收款人信息已变化。")
    debit_ok = _account_delta(session, account_id=source.id, amount_minor=-transfer.amount_minor)
    if not debit_ok:
        raise BankingRuleError("insufficient_funds", "账户余额不足，转账未执行。")
    if not _account_delta(session, account_id=destination.id, amount_minor=transfer.amount_minor):
        raise BankingRuleError("destination_not_found", "收款账户已不存在，转账未执行。")
    now = utc_now()
    session.add_all(
        [
            Transaction(
                id=uuid4(),
                account_id=source.id,
                synthetic_ref=f"transfer:{transfer.id}:out",
                direction="expense",
                entry_kind="transfer",
                amount_minor=transfer.amount_minor,
                currency=transfer.currency,
                merchant=transfer.payee_name,
                category="转账",
                description=f"转给{transfer.payee_name}",
                occurred_at=now,
            ),
            Transaction(
                id=uuid4(),
                account_id=destination.id,
                synthetic_ref=f"transfer:{transfer.id}:in",
                direction="income",
                entry_kind="transfer",
                amount_minor=transfer.amount_minor,
                currency=transfer.currency,
                merchant=transfer.payee_name,
                category="转账",
                description=f"来自{transfer.payee_name}的模拟转入",
                occurred_at=now,
            ),
        ]
    )
    transfer.status = "executed"
    transfer.executed_at = now
    session.flush()
    session.add(
        AuditEvent(
            actor_id=transfer.actor_id,
            event_type="transfer.executed",
            resource_type="transfer",
            resource_id=transfer.id,
            resource_version=transfer.version,
            request_id=request_id,
            task_id=task_id,
            tool_execution_id=tool_execution_id,
            outcome="succeeded",
            before_state={"status": "awaiting_confirmation" if task_id else "scheduled"},
            after_state={
                "status": transfer.status,
                "amount_minor": transfer.amount_minor,
                "currency": transfer.currency,
            },
        )
    )


def confirm_transfer(
    session: Session,
    *,
    actor_id: UUID,
    transfer_id: UUID,
    target_status: str,
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID,
) -> TransferView:
    transfer = session.scalar(
        select(Transfer).where(Transfer.id == transfer_id, Transfer.actor_id == actor_id)
    )
    expected_status = "scheduled" if target_status == "cancelled" else "awaiting_confirmation"
    if transfer is None or transfer.status != expected_status:
        raise BankingRuleError("transfer_state_conflict", "转账状态已变化，未执行操作。")
    if target_status == "executed" and transfer.transfer_type == "immediate":
        _execute_money_transfer(
            session,
            transfer=transfer,
            request_id=request_id,
            task_id=task_id,
            tool_execution_id=tool_execution_id,
        )
    elif target_status == "scheduled" and transfer.transfer_type == "scheduled":
        transfer.status = "scheduled"
        session.flush()
        session.add(
            AuditEvent(
                actor_id=actor_id,
                event_type="transfer.scheduled",
                resource_type="transfer",
                resource_id=transfer.id,
                resource_version=transfer.version,
                request_id=request_id,
                task_id=task_id,
                tool_execution_id=tool_execution_id,
                outcome="succeeded",
                before_state={"status": "awaiting_confirmation"},
                after_state={
                    "status": "scheduled",
                    "scheduled_at": transfer.scheduled_at.isoformat(),
                },
            )
        )
    elif target_status == "cancelled":
        if transfer.transfer_type != "scheduled" or transfer.status != "scheduled":
            raise BankingRuleError("transfer_not_cancellable", "这笔转账当前不能取消。")
        transfer.status = "cancelled"
        session.flush()
        session.add(
            AuditEvent(
                actor_id=actor_id,
                event_type="transfer.cancelled",
                resource_type="transfer",
                resource_id=transfer.id,
                resource_version=transfer.version,
                request_id=request_id,
                task_id=task_id,
                tool_execution_id=tool_execution_id,
                outcome="succeeded",
                before_state={"status": "scheduled"},
                after_state={"status": "cancelled"},
            )
        )
    else:
        raise BankingRuleError("transfer_state_conflict", "确认内容与转账类型不匹配。")
    session.flush()
    return _transfer_view(session, transfer)


def simulate_due_transfers(
    session: Session, *, actor_id: UUID, request_id: str, task_id: UUID | None = None
) -> tuple[TransferView, ...]:
    now = utc_now()
    with write_transaction(session, immediate=True):
        rows = list(
            session.scalars(
                select(Transfer)
                .where(
                    Transfer.actor_id == actor_id,
                    Transfer.transfer_type == "scheduled",
                    Transfer.status == "scheduled",
                    Transfer.scheduled_at <= now,
                )
                .order_by(Transfer.scheduled_at, Transfer.id)
            )
        )
        executed: list[Transfer] = []
        for transfer in rows:
            try:
                # A scheduled authorization cannot silently bypass a risk increase
                # on execution day. This local demo has no unattended OTP channel.
                decision = decide_risk(
                    operation="transfer",
                    amount_minor=transfer.amount_minor,
                    currency=transfer.currency,
                    daily_executed_minor=executed_transfer_total(
                        session, actor_id=actor_id, now=now
                    ),
                )
                if decision.level == "red":
                    raise BankingRuleError(
                        "strong_verification_required",
                        "定时转账在执行时达到高风险阈值，需重新授权。",
                    )
                _execute_money_transfer(
                    session,
                    transfer=transfer,
                    request_id=request_id,
                    task_id=task_id,
                    tool_execution_id=None,
                )
            except BankingRuleError as exc:
                transfer.status = "failed"
                session.flush()
                session.add(
                    AuditEvent(
                        actor_id=actor_id,
                        event_type="transfer.simulated_execution_failed",
                        resource_type="transfer",
                        resource_id=transfer.id,
                        resource_version=transfer.version,
                        request_id=request_id,
                        task_id=task_id,
                        outcome="failed",
                        before_state={"status": "scheduled"},
                        after_state={"status": "failed", "error_code": exc.code},
                    )
                )
            else:
                executed.append(transfer)
        return tuple(_transfer_view(session, item) for item in executed)


def _split_view(session: Session, bill: SplitBill) -> SplitBillView:
    participants = session.scalars(
        select(SplitParticipant)
        .where(SplitParticipant.split_bill_id == bill.id)
        .order_by(SplitParticipant.sequence)
    )
    return SplitBillView(
        id=bill.id,
        title=bill.title,
        total_amount_minor=bill.total_amount_minor,
        currency=bill.currency,
        participant_count=bill.participant_count,
        status=bill.status,
        participants=tuple(
            SplitParticipantView(row.id, row.display_name, row.amount_minor, row.status)
            for row in participants
        ),
        version=bill.version,
    )


def list_splits(session: Session, *, actor_id: UUID, limit: int = 50) -> tuple[SplitBillView, ...]:
    rows = session.scalars(
        select(SplitBill)
        .where(SplitBill.actor_id == actor_id)
        .order_by(SplitBill.created_at.desc(), SplitBill.id)
        .limit(limit)
    )
    return tuple(_split_view(session, row) for row in rows)


def propose_split(
    session: Session,
    *,
    context: ToolCallContext,
    title: str,
    amount_minor: int,
    participant_names: list[str],
    account_label: str | None = None,
) -> dict[str, object]:
    names = [name.strip() for name in participant_names]
    if any(not name for name in names) or len({_normal_name(name) for name in names}) != len(names):
        raise BankingRuleError("invalid_participants", "参与人名称不能为空且不能重复。")
    count = len(names) + 1
    try:
        shares = split_amount(amount_minor, count)
    except ValueError as exc:
        raise BankingRuleError("invalid_split", str(exc)) from exc
    account = _owned_account(session, actor_id=context.actor_id, label=account_label)
    if account.balance_minor < amount_minor:
        raise BankingRuleError("insufficient_funds", "账户余额不足，未创建分账。")
    title = title.strip() or "AA 分账"
    bill = SplitBill(
        id=uuid4(),
        actor_id=context.actor_id,
        account_id=account.id,
        title=title,
        total_amount_minor=amount_minor,
        currency=account.currency,
        participant_count=count,
        status="awaiting_confirmation",
        idempotency_key=context.execution.idempotency_key,
        version=1,
    )
    session.add(bill)
    session.flush()
    # The organizer's share is paid as part of the full simulated purchase.
    organizer = session.get(DemoUser, context.actor_id)
    if organizer is None:
        raise BankingRuleError("actor_not_found", "当前模拟用户不可用。")
    session.add(
        SplitParticipant(
            id=uuid4(),
            split_bill_id=bill.id,
            sequence=0,
            display_name=organizer.display_name,
            amount_minor=shares[0],
            status="organizer_paid",
            paid_at=utc_now(),
        )
    )
    for index, (name, share) in enumerate(zip(names, shares[1:], strict=True), start=1):
        session.add(
            SplitParticipant(
                id=uuid4(),
                split_bill_id=bill.id,
                sequence=index,
                display_name=name,
                amount_minor=share,
                status="pending",
            )
        )
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "split_bill_id": str(bill.id),
        "account_id": str(account.id),
        "title": title,
        "total_amount_minor": amount_minor,
        "participants": names,
        "shares_minor": list(shares),
        "target_status": "open",
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
        target_status="open",
        resource_type="split",
        resource_id=bill.id,
        resource_version=bill.version,
    )
    return {
        "status": "awaiting_confirmation",
        "confirmation_required": True,
        "challenge_id": challenge.id,
        "split_bill_id": bill.id,
        "title": bill.title,
        "total_amount_minor": bill.total_amount_minor,
        "currency": bill.currency,
        "participant_count": count,
        "shares_minor": list(shares),
        "participants": names,
        "current_status": "pending_confirmation",
        "target_status": "open",
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "split",
        "resource_id": bill.id,
        "resource_label": bill.title,
        "resource_version": bill.version,
    }


def propose_split_collection(
    session: Session, *, context: ToolCallContext, title: str
) -> dict[str, object]:
    bill = session.scalar(
        select(SplitBill)
        .where(
            SplitBill.actor_id == context.actor_id,
            SplitBill.status == "open",
            SplitBill.title.ilike(title.strip()),
        )
        .order_by(SplitBill.created_at.desc())
    )
    if bill is None:
        raise BankingRuleError("split_not_found", "没有找到待收款的 AA 分账。")
    participants = list(
        session.scalars(
            select(SplitParticipant)
            .where(SplitParticipant.split_bill_id == bill.id)
            .order_by(SplitParticipant.sequence)
        )
    )
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "split_bill_id": str(bill.id),
        "target_status": "settled",
        "split_bill_version": bill.version,
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
        target_status="settled",
        resource_type="split",
        resource_id=bill.id,
        resource_version=bill.version,
    )
    return {
        "status": "awaiting_confirmation",
        "confirmation_required": True,
        "challenge_id": challenge.id,
        "split_bill_id": bill.id,
        "title": bill.title,
        "total_amount_minor": bill.total_amount_minor,
        "currency": bill.currency,
        "participant_count": bill.participant_count,
        "shares_minor": [item.amount_minor for item in participants],
        "participants": [item.display_name for item in participants[1:]],
        "current_status": bill.status,
        "target_status": "settled",
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "split",
        "resource_id": bill.id,
        "resource_label": bill.title,
        "resource_version": bill.version,
    }


def confirm_split(
    session: Session,
    *,
    actor_id: UUID,
    split_bill_id: UUID,
    target_status: str,
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID,
) -> SplitBillView:
    bill = session.scalar(
        select(SplitBill).where(SplitBill.id == split_bill_id, SplitBill.actor_id == actor_id)
    )
    if bill is None:
        raise BankingRuleError("split_not_found", "没有找到当前用户的这笔 AA 分账。")
    account = session.get(Account, bill.account_id)
    if account is None or account.demo_user_id != actor_id:
        raise BankingRuleError("split_account_not_found", "分账账户不可用。")
    before = bill.status
    if target_status == "open" and bill.status == "awaiting_confirmation":
        if account.balance_minor < bill.total_amount_minor:
            raise BankingRuleError("insufficient_funds", "账户余额不足，分账没有执行。")
        if not _account_delta(
            session, account_id=account.id, amount_minor=-bill.total_amount_minor
        ):
            raise BankingRuleError("insufficient_funds", "账户余额不足，分账没有执行。")
        session.add(
            Transaction(
                id=uuid4(),
                account_id=account.id,
                synthetic_ref=f"split:{bill.id}:purchase",
                direction="expense",
                entry_kind="bill",
                amount_minor=bill.total_amount_minor,
                currency=bill.currency,
                merchant=bill.title,
                category="餐饮",
                description="模拟 AA 分账消费",
                occurred_at=utc_now(),
            )
        )
        bill.status = "open"
    elif target_status == "settled" and bill.status == "open":
        pending = list(
            session.scalars(
                select(SplitParticipant).where(
                    SplitParticipant.split_bill_id == bill.id,
                    SplitParticipant.status == "pending",
                )
            )
        )
        total = sum(item.amount_minor for item in pending)
        if total and not _account_delta(session, account_id=account.id, amount_minor=total):
            raise BankingRuleError("split_settlement_failed", "模拟收款未能写入账户，请稍后重试。")
        now = utc_now()
        for participant in pending:
            participant.status = "paid"
            participant.paid_at = now
            session.add(
                Transaction(
                    id=uuid4(),
                    account_id=account.id,
                    synthetic_ref=f"split:{bill.id}:participant:{participant.id}",
                    direction="income",
                    entry_kind="transfer",
                    amount_minor=participant.amount_minor,
                    currency=bill.currency,
                    merchant=participant.display_name,
                    category="AA分账回收",
                    description=f"收到{participant.display_name}的模拟分账款",
                    occurred_at=now,
                )
            )
        bill.status = "settled"
    else:
        raise BankingRuleError("split_state_conflict", "AA 分账状态已变化，未执行操作。")
    session.flush()
    session.add(
        AuditEvent(
            actor_id=actor_id,
            event_type="split.status_changed",
            resource_type="split",
            resource_id=bill.id,
            resource_version=bill.version,
            request_id=request_id,
            task_id=task_id,
            tool_execution_id=tool_execution_id,
            outcome="succeeded",
            before_state={"status": before},
            after_state={"status": bill.status},
        )
    )
    return _split_view(session, bill)
