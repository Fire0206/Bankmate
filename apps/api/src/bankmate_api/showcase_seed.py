"""Add deterministic synthetic records that make every BankMate page demonstrable."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from bankmate_api.agent.providers import ProviderSelection
from bankmate_api.agent.runtime import FakeProvider
from bankmate_api.application.agent import create_agent_task
from bankmate_api.application.bills import get_monthly_summary
from bankmate_api.application.risk_assessment import submit_assessment
from bankmate_api.application.subscriptions import list_subscription_reminders
from bankmate_api.domain.risk_assessment import RiskAnswers
from bankmate_api.domain.subscriptions import normalize_merchant
from bankmate_api.infrastructure.models import (
    Account,
    AgentTask,
    AuditEvent,
    Card,
    DemoUser,
    InvestmentHolding,
    InvestmentOrder,
    InvestmentProduct,
    Payee,
    RiskAssessment,
    SplitBill,
    SplitParticipant,
    Subscription,
    Transaction,
    Transfer,
)
from bankmate_api.security.demo_identity import DEMO_USER_ONE_ID
from bankmate_api.seed_data import SYNTHETIC_NAMESPACE, seed_demo_data

SHOWCASE_DATASET_VERSION = "submission-showcase-v1"
_ACTOR_ID = DEMO_USER_ONE_ID
_ACCOUNT_LABEL = "Everyday account"
_CURRENCY = "CNY"
_CONVERSATION_ID = UUID("70000000-0000-4000-8000-000000000001")


def _id(name: str) -> UUID:
    return uuid5(SYNTHETIC_NAMESPACE, f"{SHOWCASE_DATASET_VERSION}:{name}")


def _at(day: int, *, month: int = 10, hour: int = 9) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


def _owned_account(session: Session, label: str = _ACCOUNT_LABEL) -> Account:
    account = session.scalar(
        select(Account)
        .where(Account.demo_user_id == _ACTOR_ID, Account.label == label)
        .order_by(Account.id)
        .limit(1)
    )
    if account is None:
        raise RuntimeError(f"Showcase seed requires the synthetic {label!r} account.")
    return account


def _payee(session: Session, name: str) -> Payee:
    payee = session.scalar(
        select(Payee).where(Payee.actor_id == _ACTOR_ID, Payee.display_name == name)
    )
    if payee is None:
        raise RuntimeError(f"Showcase seed requires the synthetic payee {name!r}.")
    return payee


def _apply_balance_delta(account: Account, amount_minor: int) -> None:
    next_balance = account.balance_minor + amount_minor
    if next_balance < 0:
        raise RuntimeError("Showcase records would make a synthetic account negative.")
    account.balance_minor = next_balance


def _add_audit(
    session: Session,
    *,
    name: str,
    event_type: str,
    resource_type: str,
    resource_id: UUID,
    request_id: str,
    occurred_at: datetime,
    before_state: dict[str, object],
    after_state: dict[str, object],
) -> None:
    event_id = _id(f"audit:{name}")
    if session.get(AuditEvent, event_id) is not None:
        return
    session.add(
        AuditEvent(
            id=event_id,
            actor_id=_ACTOR_ID,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=2,
            request_id=request_id,
            outcome="succeeded",
            before_state=before_state,
            after_state=after_state,
            occurred_at=occurred_at,
        )
    )


def _add_transaction(
    session: Session,
    *,
    reference: str,
    account_id: UUID,
    direction: str,
    entry_kind: str,
    amount_minor: int,
    merchant: str,
    category: str,
    description: str,
    occurred_at: datetime,
    card_id: UUID | None = None,
) -> None:
    existing_id = session.scalar(
        select(Transaction.id).where(Transaction.synthetic_ref == reference)
    )
    if existing_id is not None:
        return
    session.add(
        Transaction(
            id=_id(f"transaction:{reference}"),
            account_id=account_id,
            card_id=card_id,
            synthetic_ref=reference,
            direction=direction,
            entry_kind=entry_kind,
            amount_minor=amount_minor,
            currency=_CURRENCY,
            merchant=merchant,
            category=category,
            description=description,
            occurred_at=occurred_at,
        )
    )


_BILL_FIXTURES: tuple[tuple[str, str, int, str, str, datetime], ...] = (
    ("power-oct", "expense", 26_500, "南方电网", "生活缴费", _at(20)),
    ("phone-oct", "expense", 8_800, "中国移动", "通信", _at(21)),
    ("taxi-oct", "expense", 4_600, "网约车", "交通", _at(22)),
    ("coffee-oct-2", "expense", 3_200, "咖啡工坊", "餐饮", _at(23)),
    ("groceries-oct-2", "expense", 15_600, "邻里超市", "购物", _at(24)),
    ("book-oct", "expense", 8_800, "城市书城", "文化", _at(25)),
    ("pharmacy-oct", "expense", 4_500, "安心药房", "医疗", _at(26)),
    ("reimbursement-oct", "income", 42_000, "差旅报销", "收入", _at(27)),
    ("dinner-oct", "expense", 10_800, "小满面馆", "餐饮", _at(28)),
)

_RECURRING_FIXTURES = (
    ("audio-jul", 7, 1_500, "云听书会员"),
    ("audio-aug", 8, 1_500, "云听书会员"),
    ("audio-sep", 9, 1_500, "云听书会员"),
    ("audio-oct", 10, 1_500, "云听书会员"),
    ("podcast-jul", 7, 1_200, "轻听播客会员"),
    ("podcast-aug", 8, 1_200, "轻听播客会员"),
    ("podcast-sep", 9, 1_200, "轻听播客会员"),
    ("podcast-oct", 10, 1_200, "轻听播客会员"),
)


def _seed_bills_and_subscriptions(session: Session) -> None:
    account = _owned_account(session)
    card_id = session.scalar(
        select(Transaction.card_id)
        .where(Transaction.account_id == account.id, Transaction.card_id.is_not(None))
        .order_by(Transaction.occurred_at.desc())
        .limit(1)
    )
    for reference, direction, amount_minor, merchant, category, occurred_at in _BILL_FIXTURES:
        _add_transaction(
            session,
            reference=f"submission:{reference}",
            account_id=account.id,
            card_id=card_id,
            direction=direction,
            entry_kind="bill",
            amount_minor=amount_minor,
            merchant=merchant,
            category=category,
            description=f"模拟{category}流水",
            occurred_at=occurred_at,
        )

    grouped: dict[str, list[tuple[str, int, datetime]]] = {}
    for reference, month, amount_minor, merchant in _RECURRING_FIXTURES:
        occurred_at = datetime(2026, month, 18, 2, tzinfo=UTC)
        grouped.setdefault(merchant, []).append((reference, amount_minor, occurred_at))
        _add_transaction(
            session,
            reference=f"submission:{reference}",
            account_id=account.id,
            card_id=card_id,
            direction="expense",
            entry_kind="bill",
            amount_minor=amount_minor,
            merchant=merchant,
            category="订阅",
            description="模拟周期扣费流水",
            occurred_at=occurred_at,
        )

    session.flush()
    for merchant, charges in grouped.items():
        merchant_key = normalize_merchant(merchant)
        subscription_id = uuid5(SYNTHETIC_NAMESPACE, f"subscription:{account.id}:{merchant_key}")
        if session.get(Subscription, subscription_id) is not None:
            continue
        charge_rows = sorted(charges, key=lambda row: row[2])
        _, amount_minor, last_charge_at = charge_rows[-1]
        is_paused = merchant == "轻听播客会员"
        session.add(
            Subscription(
                id=subscription_id,
                account_id=account.id,
                merchant_key=merchant_key,
                merchant=merchant,
                amount_minor=amount_minor,
                currency=_CURRENCY,
                billing_cycle="monthly",
                status="paused" if is_paused else "active",
                next_charge_at=last_charge_at + timedelta(days=30),
                reminder_days_before=7 if is_paused else 30,
                source_transaction_ids=[
                    str(_id(f"transaction:submission:{reference}"))
                    for reference, _, _ in charge_rows
                ],
                version=1,
            )
        )


def _seed_transfer_history(session: Session) -> None:
    account = _owned_account(session)
    paid_payee = _payee(session, "小林")
    paid_destination = session.get(Account, paid_payee.destination_account_id)
    scheduled_payee = _payee(session, "储蓄账户")
    if paid_destination is None:
        raise RuntimeError("Showcase seed could not resolve the synthetic transfer destination.")

    transfer_id = _id("transfer:executed")
    if session.get(Transfer, transfer_id) is None:
        occurred_at = _at(26)
        amount_minor = 52_000
        refs = (f"transfer:{transfer_id}:out", f"transfer:{transfer_id}:in")
        if session.scalar(select(Transaction.id).where(Transaction.synthetic_ref.in_(refs))):
            raise RuntimeError(
                "Partial showcase transfer ledger found; refusing to change balances."
            )
        _apply_balance_delta(account, -amount_minor)
        _apply_balance_delta(paid_destination, amount_minor)
        session.add(
            Transfer(
                id=transfer_id,
                actor_id=_ACTOR_ID,
                source_account_id=account.id,
                destination_account_id=paid_destination.id,
                payee_id=paid_payee.id,
                payee_name=paid_payee.display_name,
                remark="周末聚餐",
                amount_minor=amount_minor,
                currency=_CURRENCY,
                transfer_type="immediate",
                status="executed",
                executed_at=occurred_at,
                idempotency_key=f"{SHOWCASE_DATASET_VERSION}:transfer:executed",
                version=2,
                created_at=occurred_at,
                updated_at=occurred_at,
            )
        )
        _add_transaction(
            session,
            reference=refs[0],
            account_id=account.id,
            direction="expense",
            entry_kind="transfer",
            amount_minor=amount_minor,
            merchant=paid_payee.display_name,
            category="转账",
            description=f"转给{paid_payee.display_name}",
            occurred_at=occurred_at,
        )
        _add_transaction(
            session,
            reference=refs[1],
            account_id=paid_destination.id,
            direction="income",
            entry_kind="transfer",
            amount_minor=amount_minor,
            merchant=paid_payee.display_name,
            category="转账",
            description=f"来自{paid_payee.display_name}的模拟转入",
            occurred_at=occurred_at,
        )
        _add_audit(
            session,
            name="transfer:executed",
            event_type="transfer.executed",
            resource_type="transfer",
            resource_id=transfer_id,
            request_id=f"{SHOWCASE_DATASET_VERSION}:transfer:executed",
            occurred_at=occurred_at,
            before_state={"status": "awaiting_confirmation"},
            after_state={"status": "executed", "amount_minor": amount_minor, "currency": _CURRENCY},
        )

    scheduled_id = _id("transfer:scheduled")
    if session.get(Transfer, scheduled_id) is None:
        created_at = _at(28)
        session.add(
            Transfer(
                id=scheduled_id,
                actor_id=_ACTOR_ID,
                source_account_id=account.id,
                destination_account_id=scheduled_payee.destination_account_id,
                payee_id=scheduled_payee.id,
                payee_name=scheduled_payee.display_name,
                remark="每月储蓄",
                amount_minor=100_000,
                currency=_CURRENCY,
                transfer_type="scheduled",
                status="scheduled",
                scheduled_at=datetime(2027, 1, 15, 2, tzinfo=UTC),
                idempotency_key=f"{SHOWCASE_DATASET_VERSION}:transfer:scheduled",
                version=2,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        _add_audit(
            session,
            name="transfer:scheduled",
            event_type="transfer.scheduled",
            resource_type="transfer",
            resource_id=scheduled_id,
            request_id=f"{SHOWCASE_DATASET_VERSION}:transfer:scheduled",
            occurred_at=created_at,
            before_state={"status": "awaiting_confirmation"},
            after_state={"status": "scheduled", "amount_minor": 100_000, "currency": _CURRENCY},
        )


def _seed_split(session: Session) -> None:
    split_id = _id("split:open")
    if session.get(SplitBill, split_id) is not None:
        return
    account = _owned_account(session)
    actor = session.get(DemoUser, _ACTOR_ID)
    if actor is None:
        raise RuntimeError("Showcase seed requires the primary synthetic user.")
    amount_minor = 128_000
    participant_amount = amount_minor // 4
    occurred_at = _at(26)
    _apply_balance_delta(account, -amount_minor)
    session.add(
        SplitBill(
            id=split_id,
            actor_id=_ACTOR_ID,
            account_id=account.id,
            title="周末家庭聚餐",
            total_amount_minor=amount_minor,
            currency=_CURRENCY,
            participant_count=4,
            status="open",
            idempotency_key=f"{SHOWCASE_DATASET_VERSION}:split:open",
            version=2,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
    )
    names = (actor.display_name, "小王", "小李", "阿杰")
    for sequence, display_name in enumerate(names):
        session.add(
            SplitParticipant(
                id=_id(f"split:open:participant:{sequence}"),
                split_bill_id=split_id,
                sequence=sequence,
                display_name=display_name,
                amount_minor=participant_amount,
                status="organizer_paid" if sequence == 0 else "pending",
                paid_at=occurred_at if sequence == 0 else None,
            )
        )
    _add_transaction(
        session,
        reference=f"split:{split_id}:purchase",
        account_id=account.id,
        direction="expense",
        entry_kind="bill",
        amount_minor=amount_minor,
        merchant="周末家庭聚餐",
        category="餐饮",
        description="模拟 AA 分账消费",
        occurred_at=occurred_at,
    )
    _add_audit(
        session,
        name="split:open",
        event_type="split.status_changed",
        resource_type="split",
        resource_id=split_id,
        request_id=f"{SHOWCASE_DATASET_VERSION}:split:open",
        occurred_at=occurred_at,
        before_state={"status": "awaiting_confirmation"},
        after_state={"status": "open"},
    )


def _seed_investment_history(session: Session) -> None:
    holding_id = _id("investment:holding")
    buy_id = _id("investment:buy")
    redeem_id = _id("investment:redeem")
    if session.get(InvestmentOrder, buy_id) is not None:
        return
    account = _owned_account(session)
    product = session.scalar(select(InvestmentProduct).where(InvestmentProduct.code == "CASH-001"))
    if product is None:
        raise RuntimeError("Showcase seed requires the synthetic CASH-001 product.")

    bought_at = _at(14)
    redeemed_at = _at(22)
    purchase_amount = 300_000
    redemption_amount = 100_000
    original_units = 30_000_000
    redeemed_units = 10_000_000
    _apply_balance_delta(account, -purchase_amount + redemption_amount)
    session.add(
        InvestmentHolding(
            id=holding_id,
            actor_id=_ACTOR_ID,
            account_id=account.id,
            product_id=product.id,
            units_micros=original_units - redeemed_units,
            purchase_price_minor=product.unit_price_minor,
            version=2,
            purchased_at=bought_at,
            updated_at=redeemed_at,
        )
    )
    for order_id, order_type, amount_minor, units_micros, executed_at in (
        (buy_id, "buy", purchase_amount, original_units, bought_at),
        (redeem_id, "redeem", redemption_amount, redeemed_units, redeemed_at),
    ):
        session.add(
            InvestmentOrder(
                id=order_id,
                actor_id=_ACTOR_ID,
                account_id=account.id,
                product_id=product.id,
                holding_id=holding_id,
                order_type=order_type,
                amount_minor=amount_minor,
                units_micros=units_micros,
                currency=_CURRENCY,
                status="executed",
                idempotency_key=f"{SHOWCASE_DATASET_VERSION}:investment:{order_type}",
                version=2,
                executed_at=executed_at,
                created_at=executed_at,
                updated_at=executed_at,
            )
        )
        is_buy = order_type == "buy"
        _add_transaction(
            session,
            reference=f"investment:{order_id}",
            account_id=account.id,
            direction="expense" if is_buy else "income",
            entry_kind="investment",
            amount_minor=amount_minor,
            merchant=product.name,
            category="理财",
            description=f"模拟{'申购' if is_buy else '赎回'}{product.name}",
            occurred_at=executed_at,
        )
        _add_audit(
            session,
            name=f"investment:{order_type}",
            event_type=f"investment.{order_type}_executed",
            resource_type="investment_order",
            resource_id=order_id,
            request_id=f"{SHOWCASE_DATASET_VERSION}:investment:{order_type}",
            occurred_at=executed_at,
            before_state={"status": "awaiting_confirmation"},
            after_state={
                "status": "executed",
                "amount_minor": amount_minor,
                "units_micros": units_micros,
            },
        )


def _seed_assessment_and_agent_history(session_factory: sessionmaker[Session]) -> None:
    selection = ProviderSelection(provider=FakeProvider(), mode="fake")
    answers: RiskAnswers = {
        "time_horizon": 3,
        "loss_tolerance": 3,
        "liquidity_capacity": 3,
        "investment_experience": 3,
    }
    with session_factory() as session:
        submit_assessment(
            session,
            actor_id=_ACTOR_ID,
            answers=answers,
            idempotency_key=f"{SHOWCASE_DATASET_VERSION}:risk-assessment",
            request_id=f"{SHOWCASE_DATASET_VERSION}:risk-assessment",
        )

    requests = (
        ("cards", "查看我的银行卡"),
        ("bills", "查看2026年10月账单"),
        ("subscriptions", "查看自动扣费"),
        ("investments", "查询理财产品"),
    )
    for name, request_text in requests:
        with session_factory() as session:
            task = create_agent_task(
                session,
                actor_id=_ACTOR_ID,
                request_text=request_text,
                conversation_id=_CONVERSATION_ID,
                idempotency_key=f"{SHOWCASE_DATASET_VERSION}:agent:{name}",
                request_id=f"{SHOWCASE_DATASET_VERSION}:agent:{name}",
                selection=selection,
            )
            if task.status != "completed":
                raise RuntimeError(
                    f"The read-only showcase assistant request {name!r} did not complete: "
                    f"{task.status}."
                )


def _page_counts(session: Session) -> dict[str, int]:
    owned_accounts = select(Account.id).where(Account.demo_user_id == _ACTOR_ID)
    owned_transactions = (
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.account_id.in_(owned_accounts))
    )
    owned_bill_transactions = (
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.account_id.in_(owned_accounts),
            Transaction.entry_kind == "bill",
        )
    )
    reminder_count = len(list_subscription_reminders(session, actor_id=_ACTOR_ID, now=_at(31)))
    return {
        "总览账户": (
            session.scalar(
                select(func.count()).select_from(Account).where(Account.demo_user_id == _ACTOR_ID)
            )
            or 0
        ),
        "总览流水": session.scalar(owned_transactions) or 0,
        "助手办理记录": (
            session.scalar(
                select(func.count()).select_from(AgentTask).where(AgentTask.actor_id == _ACTOR_ID)
            )
            or 0
        ),
        "账单流水": session.scalar(owned_bill_transactions) or 0,
        "账单规则提示": len(
            get_monthly_summary(session, actor_id=_ACTOR_ID, month="2026-10").anomalies
        ),
        "银行卡": (
            session.scalar(
                select(func.count())
                .select_from(Card)
                .join(Account, Account.id == Card.account_id)
                .where(Account.demo_user_id == _ACTOR_ID)
            )
            or 0
        ),
        "转账": (
            session.scalar(
                select(func.count()).select_from(Transfer).where(Transfer.actor_id == _ACTOR_ID)
            )
            or 0
        ),
        "AA 分账": (
            session.scalar(
                select(func.count()).select_from(SplitBill).where(SplitBill.actor_id == _ACTOR_ID)
            )
            or 0
        ),
        "自动扣费": (
            session.scalar(
                select(func.count())
                .select_from(Subscription)
                .join(Account, Account.id == Subscription.account_id)
                .where(Account.demo_user_id == _ACTOR_ID)
            )
            or 0
        ),
        "续费提醒": reminder_count,
        "理财产品": session.scalar(select(func.count()).select_from(InvestmentProduct)) or 0,
        "风险测评": (
            session.scalar(
                select(func.count())
                .select_from(RiskAssessment)
                .where(RiskAssessment.actor_id == _ACTOR_ID)
            )
            or 0
        ),
        "理财持仓": (
            session.scalar(
                select(func.count())
                .select_from(InvestmentHolding)
                .where(InvestmentHolding.actor_id == _ACTOR_ID)
            )
            or 0
        ),
        "理财订单": (
            session.scalar(
                select(func.count())
                .select_from(InvestmentOrder)
                .where(InvestmentOrder.actor_id == _ACTOR_ID)
            )
            or 0
        ),
    }


def seed_submission_showcase(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Seed synthetic page data additively; do not clear or reset an existing database."""
    with session_factory.begin() as session:
        seed_demo_data(session)
        _seed_bills_and_subscriptions(session)
        _seed_transfer_history(session)
        _seed_split(session)
        _seed_investment_history(session)
    _seed_assessment_and_agent_history(session_factory)
    with session_factory() as session:
        return _page_counts(session)
