"""Synthetic birthday budget intentions; due purchases need fresh confirmation."""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch_api.agent.context import ToolCallContext
from finorch_api.application.card_controls import CATALOG
from finorch_api.application.confirmation import create_confirmation_challenge, parameters_hash
from finorch_api.application.errors import BankingRuleError
from finorch_api.application.transactions import write_transaction
from finorch_api.infrastructure.models import Account, AuditEvent, BirthdayPlan, utc_now

POLICY_VERSION = "birthday-plan-v1"
TOOL_VERSION = "1.0"
BUSINESS_TIMEZONE = timezone(timedelta(hours=8))
ITEMS = ("flowers", "cake")


def _today(now: datetime | None = None) -> date:
    return (now or utc_now()).astimezone(BUSINESS_TIMEZONE).date()


def _account(session: Session, *, actor_id: UUID, account_label: str | None) -> Account:
    statement = select(Account).where(Account.demo_user_id == actor_id, Account.currency == "CNY")
    if account_label is not None:
        statement = statement.where(Account.label == account_label.strip())
    accounts = list(session.scalars(statement.order_by(Account.created_at, Account.id).limit(2)))
    if not accounts:
        raise BankingRuleError("account_not_found", "没有找到当前用户的模拟人民币账户。")
    if account_label is None and len(accounts) > 1:
        raise BankingRuleError("account_ambiguous", "请说明从哪个账户安排生日预算。")
    return accounts[0]


def plan_details(
    session: Session, *, actor_id: UUID, plan: BirthdayPlan, now: datetime | None = None
) -> dict[str, object]:
    account = session.get(Account, plan.account_id)
    if plan.actor_id != actor_id or account is None or account.demo_user_id != actor_id:
        raise BankingRuleError("birthday_plan_not_found", "没有找到当前用户的生日计划。")
    today = _today(now)
    due = plan.status == "scheduled" and plan.purchase_on <= today
    return {
        "id": str(plan.id),
        "account_id": str(plan.account_id),
        "account_label": account.label,
        "birthday_on": plan.birthday_on.isoformat(),
        "purchase_on": plan.purchase_on.isoformat(),
        "budget_minor": plan.budget_minor,
        "catalog_total_minor": plan.catalog_total_minor,
        "currency": "CNY",
        "status": plan.status,
        "due_for_reconfirmation": due,
        "funds_held": False,
        "order_placed": False,
        "items": [
            {
                "product_code": code,
                "product_name": CATALOG[code][0],
                "unit_price_minor": CATALOG[code][1],
                "quantity": 1,
            }
            for code in ITEMS
        ],
        "next_action": (
            "到期后请重新核对余额、卡片限额和领取方式，再分别确认模拟购买。"
            if due
            else "这只是预算意向及到期提醒；资金未冻结，订单未下单。"
        ),
    }


def list_birthday_plans(
    session: Session, *, actor_id: UUID, now: datetime | None = None
) -> list[dict[str, object]]:
    rows = session.scalars(
        select(BirthdayPlan)
        .where(BirthdayPlan.actor_id == actor_id, BirthdayPlan.status == "scheduled")
        .order_by(BirthdayPlan.purchase_on, BirthdayPlan.created_at)
        .limit(100)
    )
    return [plan_details(session, actor_id=actor_id, plan=row, now=now) for row in rows]


def propose_birthday_plan(
    session: Session,
    *,
    context: ToolCallContext,
    birthday_on: date,
    budget_minor: int,
    account_label: str | None,
    now: datetime | None = None,
) -> dict[str, object]:
    today = _today(now)
    purchase_on = birthday_on - timedelta(days=2)
    if purchase_on <= today or birthday_on > today + timedelta(days=365):
        raise BankingRuleError(
            "birthday_date_invalid", "生日须在两天后至一年内，才能安排提前两天的提醒。"
        )
    catalog_total = sum(CATALOG[code][1] for code in ITEMS)
    if type(budget_minor) is not int or budget_minor < catalog_total or budget_minor > 10_000_000:
        raise BankingRuleError(
            "birthday_budget_invalid", "预算须覆盖模拟鲜花与蛋糕，且不超过 ¥100,000。"
        )
    account = _account(session, actor_id=context.actor_id, account_label=account_label)
    if account.balance_minor < budget_minor:
        raise BankingRuleError("insufficient_funds", "当前余额不足以支持这项预算意向。")
    row = BirthdayPlan(
        id=uuid4(),
        actor_id=context.actor_id,
        account_id=account.id,
        birthday_on=birthday_on,
        purchase_on=purchase_on,
        budget_minor=budget_minor,
        catalog_total_minor=catalog_total,
        status="pending_confirmation",
        version=1,
    )
    session.add(row)
    session.flush()
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "plan_id": str(row.id),
        "account_id": str(account.id),
        "birthday_on": birthday_on.isoformat(),
        "purchase_on": purchase_on.isoformat(),
        "budget_minor": budget_minor,
        "catalog_total_minor": catalog_total,
        "target_status": "scheduled",
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
        target_status="scheduled",
        resource_type="birthday_plan",
        resource_id=row.id,
        resource_version=row.version,
    )
    return {
        "status": "awaiting_confirmation",
        "confirmation_required": True,
        "challenge_id": challenge.id,
        "plan_id": row.id,
        "account_label": account.label,
        "birthday_on": birthday_on,
        "purchase_on": purchase_on,
        "budget_minor": budget_minor,
        "catalog_total_minor": catalog_total,
        "currency": "CNY",
        "items": list(ITEMS),
        "funds_held": False,
        "order_placed": False,
        "current_status": row.status,
        "target_status": "scheduled",
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "birthday_plan",
        "resource_id": row.id,
        "resource_label": "生日预算与到期提醒",
        "resource_version": row.version,
    }


def confirm_birthday_plan(
    session: Session,
    *,
    actor_id: UUID,
    plan_id: UUID,
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID,
) -> dict[str, object]:
    with write_transaction(session):
        row = session.scalar(
            select(BirthdayPlan).where(
                BirthdayPlan.id == plan_id, BirthdayPlan.actor_id == actor_id
            )
        )
        if row is None or row.status != "pending_confirmation":
            raise BankingRuleError("birthday_plan_state_conflict", "生日计划状态已变化。")
        account = _account(
            session, actor_id=actor_id, account_label=session.get(Account, row.account_id).label
        )
        if account.id != row.account_id or account.balance_minor < row.budget_minor:
            raise BankingRuleError("insufficient_funds", "账户余额已变化，无法确认这项预算意向。")
        if row.purchase_on <= _today():
            raise BankingRuleError("birthday_date_invalid", "计划日期已经到期，请重新安排。")
        row.status = "scheduled"
        row.confirmed_at = utc_now()
        session.flush()
        session.add(
            AuditEvent(
                actor_id=actor_id,
                event_type="birthday.plan_scheduled",
                resource_type="birthday_plan",
                resource_id=row.id,
                request_id=request_id,
                task_id=task_id,
                tool_execution_id=tool_execution_id,
                outcome="succeeded",
                before_state={"status": "pending_confirmation"},
                after_state={
                    "status": "scheduled",
                    "budget_minor": row.budget_minor,
                    "funds_held": False,
                    "order_placed": False,
                },
            )
        )
        session.flush()
        return plan_details(session, actor_id=actor_id, plan=row)
