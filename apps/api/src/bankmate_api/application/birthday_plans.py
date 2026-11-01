"""Persisted birthday budgets, due reminders and confirmed synthetic orders."""

from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankmate_api.agent.context import ToolCallContext
from bankmate_api.application.card_controls import CATALOG, check_card_purchase
from bankmate_api.application.confirmation import create_confirmation_challenge, parameters_hash
from bankmate_api.application.errors import BankingRuleError
from bankmate_api.application.funds import available_balance_minor
from bankmate_api.application.transactions import write_transaction
from bankmate_api.config import get_settings
from bankmate_api.infrastructure.models import (
    Account,
    AuditEvent,
    BirthdayOrder,
    BirthdayPlan,
    Card,
    CardStatus,
    ConfirmationChallenge,
    FundsReservation,
    StrongVerification,
    Transaction,
    utc_now,
)

POLICY_VERSION = "birthday-order-v1"
PLAN_POLICY_VERSION = "birthday-plan-v2"
TOOL_VERSION = "1.0"
BUSINESS_TIMEZONE = timezone(timedelta(hours=8))
PRODUCT_CODES = ("flowers", "cake")
SIMULATED_MERCHANT = "BankMate 模拟礼品商户"
SIMULATED_PICKUP = "BankMate 模拟领取点（仅演示）"


def _today(now: datetime | None = None) -> date:
    value = _effective_now(now)
    if value.tzinfo is None:
        raise ValueError("Birthday scheduling requires an aware timestamp.")
    return value.astimezone(BUSINESS_TIMEZONE).date()


def _effective_now(now: datetime | None = None) -> datetime:
    value = now or get_settings().demo_now or utc_now()
    if value.tzinfo is None:
        raise ValueError("Birthday scheduling requires an aware timestamp.")
    return value.astimezone(UTC)


def _account(session: Session, *, actor_id: UUID, account_label: str | None) -> Account:
    statement = select(Account).where(Account.demo_user_id == actor_id, Account.currency == "CNY")
    if account_label is not None:
        statement = statement.where(Account.label == account_label.strip())
    accounts = list(session.scalars(statement.order_by(Account.created_at, Account.id).limit(2)))
    if not accounts:
        raise BankingRuleError("account_not_found", "没有找到当前用户的模拟人民币账户。")
    # Match the transfer default: the first owned CNY account is shown in the
    # confirmation card, where the user can reject or cancel the proposal.
    return accounts[0]


def _active_card(
    session: Session, *, actor_id: UUID, account_id: UUID, card_suffix: str | None = None
) -> Card:
    statement = (
        select(Card)
        .join(Account, Card.account_id == Account.id)
        .where(
            Account.demo_user_id == actor_id,
            Account.id == account_id,
            Card.status == CardStatus.ACTIVE,
        )
    )
    if card_suffix is not None:
        statement = statement.where(Card.card_suffix == card_suffix)
    cards = list(session.scalars(statement.order_by(Card.created_at, Card.id).limit(2)))
    if not cards:
        raise BankingRuleError("card_unavailable", "该账户没有可用于模拟订单的正常银行卡。")
    return cards[0]


def _catalog_items() -> list[dict[str, object]]:
    return [
        {
            "product_code": code,
            "product_name": CATALOG[code][0],
            "unit_price_minor": CATALOG[code][1],
            "quantity": 1,
        }
        for code in PRODUCT_CODES
    ]


def _items_total(items: list[dict[str, object]]) -> int:
    total = 0
    for item in items:
        code = item.get("product_code")
        quantity = item.get("quantity")
        unit_price = item.get("unit_price_minor")
        if (
            not isinstance(code, str)
            or code not in CATALOG
            or type(quantity) is not int
            or quantity < 1
            or type(unit_price) is not int
            or unit_price != CATALOG[code][1]
        ):
            raise BankingRuleError(
                "birthday_catalog_changed", "模拟商品或价格已变化，请重新确认计划。"
            )
        total += unit_price * quantity
    return total


def _plan_and_children(
    session: Session, *, actor_id: UUID, plan_id: UUID
) -> tuple[BirthdayPlan, Account, Card | None, FundsReservation | None, BirthdayOrder | None]:
    plan = session.scalar(
        select(BirthdayPlan).where(BirthdayPlan.id == plan_id, BirthdayPlan.actor_id == actor_id)
    )
    if plan is None:
        raise BankingRuleError("birthday_plan_not_found", "没有找到当前用户的生日计划。")
    account = session.get(Account, plan.account_id)
    card = session.get(Card, plan.card_id) if plan.card_id is not None else None
    reservation = session.scalar(
        select(FundsReservation).where(FundsReservation.birthday_plan_id == plan.id)
    )
    order = session.scalar(select(BirthdayOrder).where(BirthdayOrder.plan_id == plan.id))
    if account is None or account.demo_user_id != actor_id:
        raise BankingRuleError("birthday_plan_not_found", "没有找到当前用户的生日计划。")
    if card is not None and card.account_id != account.id:
        raise BankingRuleError("birthday_plan_not_found", "生日计划绑定的银行卡不可用。")
    return plan, account, card, reservation, order


def plan_details(
    session: Session, *, actor_id: UUID, plan: BirthdayPlan, now: datetime | None = None
) -> dict[str, object]:
    plan, account, card, reservation, order = _plan_and_children(
        session, actor_id=actor_id, plan_id=plan.id
    )
    today = _today(now)
    held = reservation.held_minor if reservation and reservation.status == "held" else 0
    order_status = order.status if order else None
    return {
        "id": str(plan.id),
        "account_id": str(plan.account_id),
        "account_label": account.label,
        "card_suffix": card.card_suffix if card else None,
        "birthday_on": plan.birthday_on.isoformat(),
        "purchase_on": plan.purchase_on.isoformat(),
        "budget_minor": plan.budget_minor,
        "catalog_total_minor": plan.catalog_total_minor,
        "currency": "CNY",
        "status": plan.status,
        "due_for_confirmation": order_status == "awaiting_confirmation",
        "due_for_reconfirmation": order_status == "awaiting_confirmation",
        "funds_held": held > 0,
        "held_minor": held,
        "order_status": order_status,
        "order_placed": order_status == "paid",
        "order": (
            {
                "id": str(order.id),
                "merchant": order.merchant,
                "items": order.items,
                "total_amount_minor": order.total_amount_minor,
                "currency": order.currency,
                "pickup_location": order.pickup_location,
                "scheduled_for": order.scheduled_for.isoformat(),
                "status": order.status,
                "transaction_id": str(order.transaction_id) if order.transaction_id else None,
                "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            }
            if order
            else None
        ),
        "items": order.items if order else _catalog_items(),
        "next_action": (
            "订单已完成，实际扣款和流水已记录。"
            if order_status == "paid"
            else "生日预订日期已到，请核对商品、银行卡和领取信息后再次确认购买。"
            if order_status == "awaiting_confirmation"
            else "资金已预留；到期后仍需再次确认商品订单，不会自动扣款。"
            if held > 0 and plan.purchase_on > today
            else "计划已取消，预留资金已释放。"
            if plan.status == "cancelled"
            else "生日计划待处理。"
        ),
    }


def list_birthday_plans(
    session: Session, *, actor_id: UUID, now: datetime | None = None
) -> list[dict[str, object]]:
    rows = session.scalars(
        select(BirthdayPlan)
        .where(BirthdayPlan.actor_id == actor_id, BirthdayPlan.status != "pending_confirmation")
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
    card_suffix: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    today = _today(now)
    purchase_on = birthday_on - timedelta(days=2)
    if purchase_on <= today or birthday_on > today + timedelta(days=365):
        raise BankingRuleError(
            "birthday_date_invalid", "生日须在两天后至一年内，才能安排提前两天的提醒。"
        )
    items = _catalog_items()
    catalog_total = _items_total(items)
    if type(budget_minor) is not int or budget_minor < catalog_total or budget_minor > 10_000_000:
        raise BankingRuleError(
            "birthday_budget_invalid", "预算须覆盖模拟鲜花与蛋糕，且不超过 ¥100,000。"
        )
    account = _account(session, actor_id=context.actor_id, account_label=account_label)
    card = _active_card(
        session, actor_id=context.actor_id, account_id=account.id, card_suffix=card_suffix
    )
    if available_balance_minor(session, account=account) < budget_minor:
        raise BankingRuleError("insufficient_funds", "可用余额不足以预留这项生日预算。")
    row = BirthdayPlan(
        id=uuid4(),
        actor_id=context.actor_id,
        account_id=account.id,
        card_id=card.id,
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
        "card_id": str(card.id),
        "birthday_on": birthday_on.isoformat(),
        "purchase_on": purchase_on.isoformat(),
        "budget_minor": budget_minor,
        "catalog_total_minor": catalog_total,
        "items": items,
        "merchant": SIMULATED_MERCHANT,
        "pickup_location": SIMULATED_PICKUP,
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
        policy_version=PLAN_POLICY_VERSION,
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
        "card_suffix": card.card_suffix,
        "birthday_on": birthday_on,
        "purchase_on": purchase_on,
        "budget_minor": budget_minor,
        "catalog_total_minor": catalog_total,
        "currency": "CNY",
        "items": items,
        "merchant": SIMULATED_MERCHANT,
        "pickup_location": SIMULATED_PICKUP,
        "funds_held": False,
        "order_placed": False,
        "current_status": row.status,
        "target_status": "scheduled",
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "birthday_plan",
        "resource_id": row.id,
        "resource_label": "生日预算与预订计划",
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
    now: datetime | None = None,
) -> dict[str, object]:
    current = _effective_now(now)
    with write_transaction(session, immediate=True):
        plan, account, card, existing, existing_order = _plan_and_children(
            session, actor_id=actor_id, plan_id=plan_id
        )
        if plan.status != "pending_confirmation" or existing or existing_order:
            raise BankingRuleError("birthday_plan_state_conflict", "生日计划状态已变化。")
        if card is None or card.status != CardStatus.ACTIVE:
            raise BankingRuleError("card_unavailable", "银行卡状态已变化，无法预约生日订单。")
        if available_balance_minor(session, account=account) < plan.budget_minor:
            raise BankingRuleError("insufficient_funds", "可用余额已变化，无法预留这项生日预算。")
        if plan.purchase_on <= _today(now):
            raise BankingRuleError("birthday_date_invalid", "计划日期已经到期，请重新安排。")

        items = _catalog_items()
        reservation = FundsReservation(
            id=uuid4(),
            actor_id=actor_id,
            account_id=account.id,
            birthday_plan_id=plan.id,
            amount_minor=plan.budget_minor,
            held_minor=plan.budget_minor,
            consumed_minor=0,
            released_minor=0,
            currency=account.currency,
            status="held",
            version=1,
        )
        order = BirthdayOrder(
            id=uuid4(),
            actor_id=actor_id,
            plan_id=plan.id,
            account_id=account.id,
            card_id=card.id,
            merchant=SIMULATED_MERCHANT,
            items=items,
            total_amount_minor=_items_total(items),
            currency="CNY",
            pickup_location=SIMULATED_PICKUP,
            scheduled_for=plan.purchase_on,
            status="scheduled",
            version=1,
        )
        plan.status = "scheduled"
        plan.confirmed_at = current
        session.add_all([reservation, order])
        session.flush()
        after = {
            "plan_status": plan.status,
            "order_status": order.status,
            "budget_minor": plan.budget_minor,
            "held_minor": reservation.held_minor,
            "order_amount_minor": order.total_amount_minor,
            "currency": order.currency,
            "scheduled_for": order.scheduled_for.isoformat(),
            "pickup_location": order.pickup_location,
        }
        session.add_all(
            [
                AuditEvent(
                    actor_id=actor_id,
                    event_type="birthday.plan_scheduled",
                    resource_type="birthday_plan",
                    resource_id=plan.id,
                    resource_version=plan.version,
                    request_id=request_id,
                    task_id=task_id,
                    tool_execution_id=tool_execution_id,
                    outcome="succeeded",
                    before_state={"status": "pending_confirmation"},
                    after_state=after,
                ),
                AuditEvent(
                    actor_id=actor_id,
                    event_type="birthday.funds_reserved",
                    resource_type="fund_reservation",
                    resource_id=reservation.id,
                    resource_version=reservation.version,
                    request_id=request_id,
                    task_id=task_id,
                    tool_execution_id=tool_execution_id,
                    outcome="succeeded",
                    before_state={"held_minor": 0},
                    after_state={
                        "held_minor": reservation.held_minor,
                        "account_id": str(account.id),
                        "currency": reservation.currency,
                        "plan_id": str(plan.id),
                    },
                ),
                AuditEvent(
                    actor_id=actor_id,
                    event_type="birthday.order_scheduled",
                    resource_type="birthday_order",
                    resource_id=order.id,
                    resource_version=order.version,
                    request_id=request_id,
                    task_id=task_id,
                    tool_execution_id=tool_execution_id,
                    outcome="succeeded",
                    before_state=None,
                    after_state={
                        "status": order.status,
                        "amount_minor": order.total_amount_minor,
                        "scheduled_for": order.scheduled_for.isoformat(),
                        "merchant": order.merchant,
                    },
                ),
            ]
        )
        session.flush()
        return plan_details(session, actor_id=actor_id, plan=plan, now=current)


def propose_birthday_plan_change(
    session: Session,
    *,
    context: ToolCallContext,
    plan_id: UUID,
    target_status: str,
    budget_minor: int | None = None,
) -> dict[str, object]:
    plan, account, _card, reservation, order = _plan_and_children(
        session, actor_id=context.actor_id, plan_id=plan_id
    )
    if (
        plan.status != "scheduled"
        or reservation is None
        or reservation.status != "held"
        or order is None
        or order.status not in {"scheduled", "awaiting_confirmation"}
    ):
        raise BankingRuleError("birthday_plan_state_conflict", "该生日计划当前不能修改或取消。")
    if target_status == "updated":
        if (
            type(budget_minor) is not int
            or not order.total_amount_minor <= budget_minor <= 10_000_000
        ):
            raise BankingRuleError(
                "birthday_budget_invalid", "新预算必须覆盖当前商品金额，且不超过 ¥100,000。"
            )
        additional = max(0, budget_minor - reservation.held_minor)
        if (
            available_balance_minor(session, account=account, exclude_reservation_id=reservation.id)
            < additional
        ):
            raise BankingRuleError("insufficient_funds", "可用余额不足以增加这笔预留预算。")
    elif target_status != "cancelled":
        raise ValueError("Unsupported birthday plan change.")

    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "plan_id": str(plan.id),
        "plan_version": plan.version,
        "reservation_id": str(reservation.id),
        "reservation_version": reservation.version,
        "order_id": str(order.id),
        "order_version": order.version,
        "target_status": target_status,
        "budget_minor": budget_minor,
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
        policy_version=PLAN_POLICY_VERSION,
        parameters_digest=digest,
        target_status=target_status,
        resource_type="birthday_plan",
        resource_id=plan.id,
        resource_version=plan.version,
    )
    return {
        "status": "awaiting_confirmation",
        "confirmation_required": True,
        "challenge_id": challenge.id,
        "plan_id": plan.id,
        "account_label": account.label,
        "birthday_on": plan.birthday_on,
        "purchase_on": plan.purchase_on,
        "current_budget_minor": reservation.held_minor,
        "budget_minor": budget_minor,
        "current_status": plan.status,
        "target_status": target_status,
        "funds_held": reservation.held_minor > 0,
        "order_placed": False,
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "birthday_plan",
        "resource_id": plan.id,
        "resource_label": "生日预算" if target_status == "updated" else "生日计划",
        "resource_version": plan.version,
    }


def confirm_birthday_plan_change(
    session: Session,
    *,
    actor_id: UUID,
    plan_id: UUID,
    target_status: str,
    budget_minor: int | None,
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID,
    now: datetime | None = None,
) -> dict[str, object]:
    current = _effective_now(now)
    with write_transaction(session, immediate=True):
        plan, account, _card, reservation, order = _plan_and_children(
            session, actor_id=actor_id, plan_id=plan_id
        )
        if (
            plan.status != "scheduled"
            or reservation is None
            or reservation.status != "held"
            or order is None
            or order.status not in {"scheduled", "awaiting_confirmation"}
        ):
            raise BankingRuleError("birthday_plan_state_conflict", "生日计划状态已变化。")
        before = {
            "plan_status": plan.status,
            "order_status": order.status,
            "budget_minor": plan.budget_minor,
            "held_minor": reservation.held_minor,
        }
        if target_status == "updated":
            if (
                type(budget_minor) is not int
                or not order.total_amount_minor <= budget_minor <= 10_000_000
            ):
                raise BankingRuleError("birthday_budget_invalid", "新预算已无法覆盖当前商品金额。")
            additional = max(0, budget_minor - reservation.held_minor)
            if (
                available_balance_minor(
                    session, account=account, exclude_reservation_id=reservation.id
                )
                < additional
            ):
                raise BankingRuleError("insufficient_funds", "可用余额已变化，无法增加预留预算。")
            if budget_minor < reservation.held_minor:
                released = reservation.held_minor - budget_minor
                reservation.held_minor = budget_minor
                reservation.released_minor += released
            elif budget_minor > reservation.held_minor:
                increase = budget_minor - reservation.held_minor
                reservation.held_minor = budget_minor
                reservation.amount_minor += increase
            plan.budget_minor = budget_minor
            reservation.amount_minor = (
                reservation.held_minor + reservation.consumed_minor + reservation.released_minor
            )
            reservation.updated_at = current
            event_type = "birthday.budget_updated"
            target_message = "生日预算已调整，新的预留金额已生效。"
            after = {
                **before,
                "budget_minor": plan.budget_minor,
                "held_minor": reservation.held_minor,
                "released_minor": reservation.released_minor,
            }
        elif target_status == "cancelled":
            if budget_minor is not None:
                raise BankingRuleError("birthday_parameter_mismatch", "取消计划不应带入新预算。")
            released = reservation.held_minor
            reservation.held_minor = 0
            reservation.released_minor += released
            reservation.amount_minor = reservation.consumed_minor + reservation.released_minor
            reservation.status = "released"
            reservation.updated_at = current
            plan.status = "cancelled"
            order.status = "cancelled"
            for pending in session.scalars(
                select(ConfirmationChallenge).where(
                    ConfirmationChallenge.birthday_order_id == order.id,
                    ConfirmationChallenge.status == "pending",
                )
            ):
                pending.status = "cancelled"
                verification = session.scalar(
                    select(StrongVerification).where(
                        StrongVerification.confirmation_id == pending.id,
                        StrongVerification.status == "pending",
                    )
                )
                if verification is not None:
                    verification.status = "invalidated"
            event_type = "birthday.plan_cancelled"
            target_message = "生日计划已取消，剩余预留资金已释放。"
            after = {
                "plan_status": plan.status,
                "order_status": order.status,
                "held_minor": reservation.held_minor,
                "released_minor": reservation.released_minor,
            }
        else:
            raise ValueError("Unsupported birthday plan change.")
        session.add(
            AuditEvent(
                actor_id=actor_id,
                event_type=event_type,
                resource_type="birthday_plan",
                resource_id=plan.id,
                resource_version=plan.version,
                request_id=request_id,
                task_id=task_id,
                tool_execution_id=tool_execution_id,
                outcome="succeeded",
                before_state=before,
                after_state=after,
            )
        )
        session.flush()
        return {
            "status": "completed",
            "message": target_message,
            **plan_details(session, actor_id=actor_id, plan=plan, now=current),
        }


def dispatch_due_birthday_orders(session: Session, *, now: datetime) -> int:
    """Persist due reminders once; never charges or authorizes a purchase."""
    if now.tzinfo is None:
        raise ValueError("Birthday scheduler requires an aware timestamp.")
    due_date = _today(now)
    count = 0
    with write_transaction(session, immediate=True):
        due = list(
            session.scalars(
                select(BirthdayOrder)
                .where(
                    BirthdayOrder.status == "scheduled",
                    BirthdayOrder.scheduled_for <= due_date,
                )
                .order_by(BirthdayOrder.scheduled_for, BirthdayOrder.id)
            )
        )
        for order in due:
            plan, account, card, reservation, _ = _plan_and_children(
                session, actor_id=order.actor_id, plan_id=order.plan_id
            )
            if (
                plan.status != "scheduled"
                or reservation is None
                or reservation.status != "held"
                or reservation.held_minor < order.total_amount_minor
                or card is None
            ):
                order.status = "failed"
                outcome = "failed"
                error_code = "birthday_schedule_integrity_error"
            else:
                order.status = "awaiting_confirmation"
                order.due_notified_at = now
                outcome = "awaiting_confirmation"
                error_code = None
            session.flush()
            session.add(
                AuditEvent(
                    actor_id=order.actor_id,
                    event_type="birthday.order_due",
                    resource_type="birthday_order",
                    resource_id=order.id,
                    resource_version=order.version,
                    request_id="birthday-scheduler",
                    outcome=outcome,
                    before_state={"status": "scheduled"},
                    after_state={
                        "status": order.status,
                        "scheduled_for": order.scheduled_for.isoformat(),
                        "error_code": error_code,
                    },
                )
            )
            count += 1
        session.flush()
    return count


def propose_birthday_order(
    session: Session,
    *,
    context: ToolCallContext,
    plan_id: UUID,
    now: datetime | None = None,
) -> dict[str, object]:
    current = _effective_now(now)
    plan, account, card, reservation, order = _plan_and_children(
        session, actor_id=context.actor_id, plan_id=plan_id
    )
    if order is None or reservation is None or card is None:
        raise BankingRuleError("birthday_order_not_found", "该生日计划没有可执行的模拟订单。")
    if order.status != "awaiting_confirmation" or order.scheduled_for > _today(current):
        raise BankingRuleError("birthday_order_not_due", "模拟订单尚未到预订日期，不能提前购买。")
    if plan.status != "scheduled" or reservation.status != "held":
        raise BankingRuleError("birthday_order_state_conflict", "生日计划或预算预留状态已变化。")
    if card.status != CardStatus.ACTIVE:
        raise BankingRuleError("card_unavailable", "预订银行卡当前不可用，请先核对卡片状态。")
    if account.currency != order.currency or account.demo_user_id != context.actor_id:
        raise BankingRuleError("birthday_order_conflict", "模拟订单账户信息已变化。")
    if reservation.held_minor < order.total_amount_minor:
        raise BankingRuleError("birthday_budget_insufficient", "预留金额不足，未创建购买确认。")
    if (
        available_balance_minor(session, account=account, exclude_reservation_id=reservation.id)
        < order.total_amount_minor
    ):
        raise BankingRuleError("insufficient_funds", "账户余额不足以覆盖其他预留和本次订单。")
    if _items_total(order.items) != order.total_amount_minor:
        raise BankingRuleError("birthday_catalog_changed", "模拟商品价格已变化，请重新确认商品。")
    check_card_purchase(
        session,
        card=card,
        amount_minor=order.total_amount_minor,
        channel="online",
        now=current,
    )
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "plan_id": str(plan.id),
        "order_id": str(order.id),
        "reservation_id": str(reservation.id),
        "account_id": str(account.id),
        "card_id": str(card.id),
        "card_version": card.version,
        "order_version": order.version,
        "reservation_version": reservation.version,
        "items": order.items,
        "amount_minor": order.total_amount_minor,
        "currency": order.currency,
        "merchant": order.merchant,
        "pickup_location": order.pickup_location,
        "scheduled_for": order.scheduled_for.isoformat(),
        "target_status": "paid",
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
        target_status="paid",
        resource_type="birthday_order",
        resource_id=order.id,
        resource_version=order.version,
    )
    return {
        "status": "awaiting_confirmation",
        "confirmation_required": True,
        "challenge_id": challenge.id,
        "plan_id": plan.id,
        "order_id": order.id,
        "account_label": account.label,
        "card_suffix": card.card_suffix,
        "birthday_on": plan.birthday_on,
        "scheduled_for": order.scheduled_for,
        "items": order.items,
        "amount_minor": order.total_amount_minor,
        "currency": order.currency,
        "merchant": order.merchant,
        "pickup_location": order.pickup_location,
        "held_minor": reservation.held_minor,
        "current_status": order.status,
        "target_status": "paid",
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "birthday_order",
        "resource_id": order.id,
        "resource_label": "生日礼品模拟订单",
        "resource_version": order.version,
    }


def confirm_birthday_order(
    session: Session,
    *,
    actor_id: UUID,
    order_id: UUID,
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID,
    now: datetime | None = None,
) -> dict[str, object]:
    current = _effective_now(now)
    with write_transaction(session, immediate=True):
        order = session.scalar(
            select(BirthdayOrder).where(
                BirthdayOrder.id == order_id, BirthdayOrder.actor_id == actor_id
            )
        )
        if order is None or order.status != "awaiting_confirmation":
            raise BankingRuleError("birthday_order_state_conflict", "模拟订单状态已变化，未购买。")
        plan, account, card, reservation, _ = _plan_and_children(
            session, actor_id=actor_id, plan_id=order.plan_id
        )
        if (
            plan.status != "scheduled"
            or account.id != order.account_id
            or card is None
            or card.id != order.card_id
            or reservation is None
            or reservation.status != "held"
        ):
            raise BankingRuleError("birthday_order_conflict", "预订计划或预留资金已变化，未购买。")
        if order.scheduled_for > _today(current):
            raise BankingRuleError("birthday_order_not_due", "模拟订单尚未到预订日期。")
        total = _items_total(order.items)
        if total != order.total_amount_minor or total > plan.budget_minor:
            raise BankingRuleError("birthday_catalog_changed", "商品价格或预算已变化，未扣款。")
        if reservation.held_minor < total:
            raise BankingRuleError("birthday_budget_insufficient", "预留金额不足，未扣款。")
        if (
            available_balance_minor(session, account=account, exclude_reservation_id=reservation.id)
            < total
        ):
            raise BankingRuleError("insufficient_funds", "账户余额不足以覆盖其他预留和本次订单。")
        check_card_purchase(session, card=card, amount_minor=total, channel="online", now=current)

        before = {
            "order_status": order.status,
            "plan_status": plan.status,
            "balance_minor": account.balance_minor,
            "held_minor": reservation.held_minor,
        }
        order.status = "confirmed"
        order.confirmed_at = current
        session.flush()
        account.balance_minor -= total
        account.version += 1
        account.updated_at = current
        transaction = Transaction(
            id=uuid4(),
            account_id=account.id,
            card_id=card.id,
            synthetic_ref=f"birthday-order:{order.id}",
            direction="expense",
            entry_kind="bill",
            amount_minor=total,
            currency=order.currency,
            merchant=order.merchant,
            category="礼品",
            description="生日鲜花与蛋糕模拟订单",
            occurred_at=current,
        )
        session.add(transaction)
        # Materialize the referenced ledger row before writing its foreign key
        # back onto the order; SQLite enforces the constraint on each statement.
        session.flush()
        reservation.consumed_minor += total
        excess = reservation.held_minor - total
        reservation.held_minor = 0
        reservation.released_minor += excess
        reservation.status = "consumed"
        reservation.updated_at = current
        order.status = "paid"
        order.transaction_id = transaction.id
        order.paid_at = current
        plan.status = "completed"
        session.flush()
        after = {
            "order_status": order.status,
            "plan_status": plan.status,
            "amount_minor": total,
            "currency": order.currency,
            "transaction_id": str(transaction.id),
            "balance_minor": account.balance_minor,
            "held_minor": reservation.held_minor,
            "consumed_minor": reservation.consumed_minor,
            "released_minor": reservation.released_minor,
        }
        events = [
            AuditEvent(
                actor_id=actor_id,
                event_type="birthday.funds_consumed",
                resource_type="fund_reservation",
                resource_id=reservation.id,
                resource_version=reservation.version,
                request_id=request_id,
                task_id=task_id,
                tool_execution_id=tool_execution_id,
                outcome="succeeded",
                before_state={"held_minor": before["held_minor"]},
                after_state={
                    "consumed_minor": reservation.consumed_minor,
                    "held_minor": reservation.held_minor,
                    "order_id": str(order.id),
                },
            ),
            AuditEvent(
                actor_id=actor_id,
                event_type="birthday.order_paid",
                resource_type="birthday_order",
                resource_id=order.id,
                resource_version=order.version,
                request_id=request_id,
                task_id=task_id,
                tool_execution_id=tool_execution_id,
                outcome="succeeded",
                before_state={"status": "confirmed", "balance_minor": before["balance_minor"]},
                after_state=after,
            ),
        ]
        if excess:
            events.append(
                AuditEvent(
                    actor_id=actor_id,
                    event_type="birthday.funds_released",
                    resource_type="fund_reservation",
                    resource_id=reservation.id,
                    resource_version=reservation.version,
                    request_id=request_id,
                    task_id=task_id,
                    tool_execution_id=tool_execution_id,
                    outcome="succeeded",
                    before_state={"held_minor": before["held_minor"]},
                    after_state={"released_minor": excess, "held_minor": reservation.held_minor},
                )
            )
        session.add_all(events)
        session.flush()
        return plan_details(session, actor_id=actor_id, plan=plan, now=current)
