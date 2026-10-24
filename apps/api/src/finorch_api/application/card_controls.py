"""Bounded synthetic card controls and catalog purchases; no external payment network."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from finorch_api.agent.context import ToolCallContext
from finorch_api.application.confirmation import create_confirmation_challenge, parameters_hash
from finorch_api.application.errors import BankingRuleError
from finorch_api.infrastructure.models import Account, AuditEvent, Card, Transaction, utc_now
from finorch_api.security.risk_policy import business_day_bounds

POLICY_VERSION = "card-controls-v1"
TOOL_VERSION = "1.0"
CATALOG: dict[str, tuple[str, int]] = {
    "flowers": ("模拟鲜花", 29_900),
    "cake": ("模拟蛋糕", 19_900),
}


def _owned_suffix(session: Session, *, actor_id: UUID, suffix: str) -> Card:
    cards = list(
        session.scalars(
            select(Card)
            .join(Account, Card.account_id == Account.id)
            .where(Account.demo_user_id == actor_id, Card.card_suffix == suffix)
        )
    )
    if len(cards) != 1:
        raise BankingRuleError("card_not_found", "没有找到当前用户的指定模拟银行卡。")
    return cards[0]


def _challenge(
    session: Session,
    *,
    context: ToolCallContext,
    card: Card,
    target_status: str,
    parameters: dict[str, object],
    details: dict[str, object],
) -> dict[str, object]:
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "card_id": str(card.id),
        "target_status": target_status,
        **parameters,
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
        target_status=target_status,
        resource_type="card",
        resource_id=card.id,
        resource_version=card.version,
    )
    return {
        "status": "awaiting_confirmation",
        "confirmation_required": True,
        "challenge_id": challenge.id,
        "card_id": card.id,
        "card_suffix": card.card_suffix,
        "card_label": card.label,
        "current_status": card.status.value,
        "target_status": target_status,
        "card_version": card.version,
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "card",
        "resource_id": card.id,
        "resource_label": card.label,
        "resource_version": card.version,
        **details,
    }


def propose_card_controls(
    session: Session,
    *,
    context: ToolCallContext,
    card_suffix: str,
    single_limit_minor: int | None,
    daily_limit_minor: int | None,
    online_enabled: bool | None,
) -> dict[str, object]:
    card = _owned_suffix(session, actor_id=context.actor_id, suffix=card_suffix)
    if card.status.value not in {"active", "frozen"}:
        raise BankingRuleError("card_unavailable", "已挂失或停用的卡不能调整消费设置。")
    single = single_limit_minor if single_limit_minor is not None else card.single_limit_minor
    daily = daily_limit_minor if daily_limit_minor is not None else card.daily_limit_minor
    online = online_enabled if online_enabled is not None else card.online_enabled
    if type(single) is not int or type(daily) is not int or single <= 0 or daily <= 0:
        raise BankingRuleError("invalid_card_limit", "限额必须是正整数分。")
    if single > daily or daily > 10_000_000:
        raise BankingRuleError("invalid_card_limit", "单笔限额不得超过单日限额。")
    if (single, daily, online) == (
        card.single_limit_minor,
        card.daily_limit_minor,
        card.online_enabled,
    ):
        raise BankingRuleError("card_controls_unchanged", "卡片消费设置没有变化。")
    parameters = {
        "single_limit_minor": single,
        "daily_limit_minor": daily,
        "online_enabled": online,
    }
    return _challenge(
        session,
        context=context,
        card=card,
        target_status="updated",
        parameters=parameters,
        details=parameters,
    )


def propose_card_purchase(
    session: Session,
    *,
    context: ToolCallContext,
    card_suffix: str,
    product_code: str,
    quantity: int,
    channel: str,
) -> dict[str, object]:
    card = _owned_suffix(session, actor_id=context.actor_id, suffix=card_suffix)
    if product_code not in CATALOG or quantity not in range(1, 4):
        raise BankingRuleError("invalid_catalog_item", "仅支持目录中的合成商品和 1–3 件数量。")
    product_name, price = CATALOG[product_code]
    amount = price * quantity
    check_card_purchase(session, card=card, amount_minor=amount, channel=channel, now=utc_now())
    parameters = {
        "product_code": product_code,
        "quantity": quantity,
        "channel": channel,
        "amount_minor": amount,
    }
    return _challenge(
        session,
        context=context,
        card=card,
        target_status="executed",
        parameters=parameters,
        details={**parameters, "product_name": product_name},
    )


def check_card_purchase(
    session: Session,
    *,
    card: Card,
    amount_minor: int,
    channel: str,
    now: datetime,
) -> None:
    if card.status.value != "active":
        raise BankingRuleError("card_unavailable", "卡片当前不可用于模拟消费。")
    if channel not in {"online", "in_store"}:
        raise BankingRuleError("invalid_card_channel", "模拟消费渠道无效。")
    if channel == "online" and not card.online_enabled:
        raise BankingRuleError("card_online_disabled", "这张卡已关闭线上模拟消费。")
    if amount_minor > card.single_limit_minor:
        raise BankingRuleError("card_single_limit_exceeded", "超过模拟卡单笔消费限额。")
    start, end = business_day_bounds(now)
    spent = int(
        session.scalar(
            select(func.coalesce(func.sum(Transaction.amount_minor), 0)).where(
                Transaction.card_id == card.id,
                Transaction.direction == "expense",
                Transaction.entry_kind == "bill",
                Transaction.occurred_at >= start,
                Transaction.occurred_at < end,
            )
        )
        or 0
    )
    if spent + amount_minor > card.daily_limit_minor:
        raise BankingRuleError("card_daily_limit_exceeded", "超过模拟卡当日消费限额。")


def execute_card_controls(
    session: Session,
    *,
    card: Card,
    actor_id: UUID,
    details: dict[str, object],
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID,
) -> dict[str, object]:
    before = {
        "single_limit_minor": card.single_limit_minor,
        "daily_limit_minor": card.daily_limit_minor,
        "online_enabled": card.online_enabled,
    }
    card.single_limit_minor = int(details["single_limit_minor"])
    card.daily_limit_minor = int(details["daily_limit_minor"])
    card.online_enabled = bool(details["online_enabled"])
    card.updated_at = utc_now()
    session.flush()
    after = {
        **before,
        **{
            "single_limit_minor": card.single_limit_minor,
            "daily_limit_minor": card.daily_limit_minor,
            "online_enabled": card.online_enabled,
        },
    }
    session.add(
        AuditEvent(
            actor_id=actor_id,
            card_id=card.id,
            event_type="card.controls_changed",
            resource_type="card",
            resource_id=card.id,
            resource_version=card.version,
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
        "card_suffix": card.card_suffix,
        "card": {
            "card_suffix": card.card_suffix,
            "single_limit_minor": card.single_limit_minor,
            "daily_limit_minor": card.daily_limit_minor,
            "online_enabled": card.online_enabled,
            "status": card.status.value,
        },
    }


def execute_card_purchase(
    session: Session,
    *,
    card: Card,
    actor_id: UUID,
    details: dict[str, object],
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID,
) -> dict[str, object]:
    code = str(details["product_code"])
    quantity = int(details["quantity"])
    channel = str(details["channel"])
    product_name, price = CATALOG[code]
    amount = price * quantity
    if amount != details["amount_minor"]:
        raise BankingRuleError("catalog_price_changed", "模拟商品价格已变化，请重新确认。")
    now = utc_now()
    check_card_purchase(session, card=card, amount_minor=amount, channel=channel, now=now)
    account = session.scalar(
        select(Account).where(Account.id == card.account_id, Account.demo_user_id == actor_id)
    )
    if account is None or account.currency != "CNY":
        raise BankingRuleError("account_not_found", "卡片绑定账户不可用。")
    debit = session.execute(
        update(Account)
        .where(Account.id == account.id, Account.balance_minor >= amount)
        .values(
            balance_minor=Account.balance_minor - amount,
            version=Account.version + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if debit.rowcount != 1:
        raise BankingRuleError("insufficient_funds", "模拟账户余额不足，消费未执行。")
    session.expire(account, ["balance_minor", "version", "updated_at"])
    transaction = Transaction(
        id=uuid4(),
        account_id=account.id,
        card_id=card.id,
        synthetic_ref=f"card-purchase:{tool_execution_id}",
        direction="expense",
        entry_kind="bill",
        amount_minor=amount,
        currency="CNY",
        merchant=product_name,
        category="礼品",
        description=f"{product_name} × {quantity}（模拟）",
        occurred_at=now,
    )
    session.add(transaction)
    card.updated_at = now
    session.flush()
    session.add(
        AuditEvent(
            actor_id=actor_id,
            card_id=card.id,
            event_type="card.purchase_executed",
            resource_type="transaction",
            resource_id=transaction.id,
            request_id=request_id,
            task_id=task_id,
            tool_execution_id=tool_execution_id,
            outcome="succeeded",
            after_state={
                "card_id": str(card.id),
                "product_code": code,
                "quantity": quantity,
                "amount_minor": amount,
                "currency": "CNY",
                "channel": channel,
                "account_balance_minor": account.balance_minor,
            },
        )
    )
    session.flush()
    return {
        "card_suffix": card.card_suffix,
        "product_code": code,
        "product_name": product_name,
        "quantity": quantity,
        "amount_minor": amount,
        "currency": "CNY",
        "channel": channel,
        "transaction_id": str(transaction.id),
        "account_balance_minor": account.balance_minor,
    }
