from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from finorch_api.agent.context import ToolCallContext
from finorch_api.application.confirmation import create_confirmation_challenge, parameters_hash
from finorch_api.application.errors import BankingRuleError
from finorch_api.domain.investments import product_is_suitable, units_for_amount, value_for_units
from finorch_api.infrastructure.models import (
    Account,
    AuditEvent,
    DemoUser,
    InvestmentHolding,
    InvestmentOrder,
    InvestmentProduct,
    Transaction,
    utc_now,
)

POLICY_VERSION = "investment-confirmation-v1"


@dataclass(frozen=True)
class ProductView:
    id: UUID
    code: str
    name: str
    category: str
    risk_level: int
    minimum_amount_minor: int
    unit_price_minor: int
    annual_yield_bps: int
    term_days: int
    currency: str
    description: str
    suitable: bool


@dataclass(frozen=True)
class HoldingView:
    id: UUID
    product_id: UUID
    product_name: str
    units_micros: int
    purchase_price_minor: int
    current_price_minor: int
    current_value_minor: int
    estimated_gain_minor: int
    currency: str
    version: int


@dataclass(frozen=True)
class InvestmentOrderView:
    id: UUID
    order_type: str
    product_id: UUID
    product_name: str
    amount_minor: int
    currency: str
    status: str
    executed_at: datetime | None
    holding_id: UUID | None


@dataclass(frozen=True)
class PortfolioView:
    currency: str
    cash_balance_minor: int
    invested_value_minor: int
    estimated_gain_minor: int
    total_assets_minor: int
    risk_level: int
    risk_label: str
    holdings: tuple[HoldingView, ...]


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _product_view(product: InvestmentProduct, *, user_risk_level: int) -> ProductView:
    return ProductView(
        id=product.id,
        code=product.code,
        name=product.name,
        category=product.category,
        risk_level=product.risk_level,
        minimum_amount_minor=product.minimum_amount_minor,
        unit_price_minor=product.unit_price_minor,
        annual_yield_bps=product.annual_yield_bps,
        term_days=product.term_days,
        currency=product.currency,
        description=product.description,
        suitable=product_is_suitable(
            user_risk_level=user_risk_level, product_risk_level=product.risk_level
        ),
    )


def get_risk_profile(session: Session, *, actor_id: UUID) -> tuple[int, str]:
    user = session.get(DemoUser, actor_id)
    if user is None:
        raise BankingRuleError("actor_not_found", "当前模拟用户不可用。")
    labels = {1: "保守型", 2: "稳健型", 3: "平衡型", 4: "成长型", 5: "进取型"}
    return user.risk_level, labels[user.risk_level]


def list_products(
    session: Session,
    *,
    actor_id: UUID,
    category: str | None = None,
    maximum_risk_level: int | None = None,
) -> tuple[ProductView, ...]:
    user = session.get(DemoUser, actor_id)
    if user is None:
        raise BankingRuleError("actor_not_found", "当前模拟用户不可用。")
    statement = select(InvestmentProduct).order_by(
        InvestmentProduct.risk_level, InvestmentProduct.name
    )
    if category:
        statement = statement.where(InvestmentProduct.category.ilike(category.strip()))
    if maximum_risk_level is not None:
        statement = statement.where(InvestmentProduct.risk_level <= maximum_risk_level)
    return tuple(
        _product_view(item, user_risk_level=user.risk_level) for item in session.scalars(statement)
    )


def _product_by_name(session: Session, *, name: str) -> InvestmentProduct:
    normalized = "".join(name.casefold().split())
    rows = list(
        session.scalars(
            select(InvestmentProduct).where(
                InvestmentProduct.name.ilike(f"%{name.strip()}%")
                | InvestmentProduct.code.ilike(f"%{name.strip()}%")
            )
        )
    )
    if not rows:
        raise BankingRuleError("product_not_found", "没有找到匹配的模拟理财产品。")
    if len(rows) > 1 and not any(
        "".join(row.name.casefold().split()) == normalized for row in rows
    ):
        raise BankingRuleError("ambiguous_product", "产品名称匹配多项，请说出完整名称。")
    return next(
        (row for row in rows if "".join(row.name.casefold().split()) == normalized), rows[0]
    )


def _owned_account(session: Session, *, actor_id: UUID, label: str | None) -> Account:
    statement = select(Account).where(Account.demo_user_id == actor_id)
    if label:
        statement = statement.where(Account.label.ilike(label.strip()))
    account = session.scalar(statement.order_by(Account.created_at, Account.id).limit(1))
    if account is None:
        raise BankingRuleError("account_not_found", "没有找到当前模拟用户的指定账户。")
    return account


def _propose_order(
    session: Session,
    *,
    context: ToolCallContext,
    order_type: str,
    product_name: str,
    amount_minor: int | None,
    account_label: str | None = None,
    holding_id: UUID | None = None,
) -> dict[str, object]:
    if order_type == "buy":
        product = _product_by_name(session, name=product_name)
        account = _owned_account(session, actor_id=context.actor_id, label=account_label)
        user = session.get(DemoUser, context.actor_id)
        if user is None:
            raise BankingRuleError("actor_not_found", "当前模拟用户不可用。")
        if not product_is_suitable(
            user_risk_level=user.risk_level, product_risk_level=product.risk_level
        ):
            raise BankingRuleError("risk_mismatch", "产品风险等级高于当前模拟用户的风险承受等级。")
        if amount_minor is None or amount_minor < product.minimum_amount_minor:
            raise BankingRuleError("below_minimum", "申购金额低于产品起购金额。")
        if account.currency != product.currency:
            raise BankingRuleError("currency_mismatch", "账户与理财产品的币种不一致。")
        if account.balance_minor < amount_minor:
            raise BankingRuleError("insufficient_funds", "账户余额不足，未创建申购。")
        units = units_for_amount(
            amount_minor=amount_minor, unit_price_minor=product.unit_price_minor
        )
        holding = None
    else:
        if holding_id is not None:
            holding = session.scalar(
                select(InvestmentHolding).where(
                    InvestmentHolding.id == holding_id,
                    InvestmentHolding.actor_id == context.actor_id,
                )
            )
        else:
            product = _product_by_name(session, name=product_name)
            holding = session.scalar(
                select(InvestmentHolding)
                .where(
                    InvestmentHolding.actor_id == context.actor_id,
                    InvestmentHolding.product_id == product.id,
                    InvestmentHolding.units_micros > 0,
                )
                .order_by(InvestmentHolding.purchased_at)
            )
        if holding is None:
            raise BankingRuleError("holding_not_found", "没有找到当前用户的可赎回持仓。")
        product = session.get(InvestmentProduct, holding.product_id)
        account = session.get(Account, holding.account_id)
        if product is None or account is None or account.demo_user_id != context.actor_id:
            raise BankingRuleError("holding_not_found", "没有找到当前用户的可赎回持仓。")
        holding_value = value_for_units(
            units_micros=holding.units_micros, unit_price_minor=product.unit_price_minor
        )
        redeem_amount = holding_value if amount_minor is None else amount_minor
        if redeem_amount <= 0 or redeem_amount > holding_value:
            raise BankingRuleError("redeem_amount_invalid", "赎回金额超出当前模拟持仓价值。")
        units = min(holding.units_micros, redeem_amount * 1_000_000 // product.unit_price_minor)
        if amount_minor is None:
            units = holding.units_micros
        if units <= 0:
            raise BankingRuleError("redeem_amount_invalid", "赎回金额不足以兑换最小模拟份额。")
        redeem_amount = value_for_units(
            units_micros=units, unit_price_minor=product.unit_price_minor
        )
        amount_minor = redeem_amount

    if amount_minor is None or amount_minor <= 0:
        raise BankingRuleError("invalid_amount", "理财金额必须大于零。")
    order = InvestmentOrder(
        id=uuid4(),
        actor_id=context.actor_id,
        account_id=account.id,
        product_id=product.id,
        holding_id=holding.id if holding else None,
        order_type=order_type,
        amount_minor=amount_minor,
        units_micros=units,
        currency=product.currency,
        status="awaiting_confirmation",
        idempotency_key=context.execution.idempotency_key,
        version=1,
    )
    session.add(order)
    session.flush()
    normalized = {
        "tool_name": context.execution.tool_name,
        "tool_version": context.execution.tool_version,
        "order_id": str(order.id),
        "order_type": order_type,
        "account_id": str(account.id),
        "product_id": str(product.id),
        "holding_id": str(holding.id) if holding else None,
        "amount_minor": order.amount_minor,
        "units_micros": order.units_micros,
        "unit_price_minor": product.unit_price_minor,
        "target_status": "executed",
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
        target_status="executed",
        resource_type="investment_order",
        resource_id=order.id,
        resource_version=order.version,
    )
    return {
        "status": "awaiting_confirmation",
        "confirmation_required": True,
        "challenge_id": challenge.id,
        "order_id": order.id,
        "order_type": order_type,
        "product_id": product.id,
        "product_name": product.name,
        "account_label": account.label,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "units_micros": order.units_micros,
        "risk_level": product.risk_level,
        "current_status": "pending_confirmation",
        "target_status": "executed",
        "parameters_hash": digest,
        "idempotency_key": challenge.idempotency_key,
        "expires_at": challenge.expires_at,
        "resource_type": "investment_order",
        "resource_id": order.id,
        "resource_label": product.name,
        "resource_version": order.version,
    }


def propose_purchase(
    session: Session,
    *,
    context: ToolCallContext,
    product_name: str,
    amount_minor: int,
    account_label: str | None = None,
) -> dict[str, object]:
    return _propose_order(
        session,
        context=context,
        order_type="buy",
        product_name=product_name,
        amount_minor=amount_minor,
        account_label=account_label,
    )


def propose_redemption(
    session: Session,
    *,
    context: ToolCallContext,
    product_name: str,
    amount_minor: int | None = None,
    holding_id: UUID | None = None,
) -> dict[str, object]:
    return _propose_order(
        session,
        context=context,
        order_type="redeem",
        product_name=product_name,
        amount_minor=amount_minor,
        holding_id=holding_id,
    )


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


def confirm_order(
    session: Session,
    *,
    actor_id: UUID,
    order_id: UUID,
    request_id: str,
    task_id: UUID,
    tool_execution_id: UUID,
) -> InvestmentOrderView:
    order = session.scalar(
        select(InvestmentOrder).where(
            InvestmentOrder.id == order_id, InvestmentOrder.actor_id == actor_id
        )
    )
    if order is None or order.status != "awaiting_confirmation":
        raise BankingRuleError("investment_order_conflict", "理财订单状态已变化，未执行。")
    product = session.get(InvestmentProduct, order.product_id)
    account = session.get(Account, order.account_id)
    if product is None or account is None or account.demo_user_id != actor_id:
        raise BankingRuleError("investment_order_conflict", "理财订单账户或产品不可用。")
    if order.order_type == "buy":
        user = session.get(DemoUser, actor_id)
        if user is None or not product_is_suitable(
            user_risk_level=user.risk_level, product_risk_level=product.risk_level
        ):
            raise BankingRuleError("risk_mismatch", "产品风险等级与当前用户风险等级不匹配。")
        if account.balance_minor < order.amount_minor:
            raise BankingRuleError("insufficient_funds", "账户余额不足，申购没有执行。")
        if not _account_delta(session, account_id=account.id, amount_minor=-order.amount_minor):
            raise BankingRuleError("insufficient_funds", "账户余额不足，申购没有执行。")
        holding = InvestmentHolding(
            id=uuid4(),
            actor_id=actor_id,
            account_id=account.id,
            product_id=product.id,
            units_micros=order.units_micros,
            purchase_price_minor=product.unit_price_minor,
            version=1,
            purchased_at=utc_now(),
        )
        session.add(holding)
        order.holding_id = holding.id
        direction = "expense"
        description = f"模拟申购{product.name}"
    elif order.order_type == "redeem":
        holding = session.scalar(
            select(InvestmentHolding).where(
                InvestmentHolding.id == order.holding_id,
                InvestmentHolding.actor_id == actor_id,
            )
        )
        if holding is None or holding.units_micros < order.units_micros:
            raise BankingRuleError("holding_version_conflict", "持仓已变化，请重新读取后操作。")
        if not _account_delta(session, account_id=account.id, amount_minor=order.amount_minor):
            raise BankingRuleError("account_not_found", "模拟账户不可用，赎回没有执行。")
        holding.units_micros -= order.units_micros
        direction = "income"
        description = f"模拟赎回{product.name}"
    else:
        raise BankingRuleError("investment_order_conflict", "理财订单类型无效。")

    now = utc_now()
    session.add(
        Transaction(
            id=uuid4(),
            account_id=account.id,
            synthetic_ref=f"investment:{order.id}",
            direction=direction,
            entry_kind="investment",
            amount_minor=order.amount_minor,
            currency=order.currency,
            merchant=product.name,
            category="理财",
            description=description,
            occurred_at=now,
        )
    )
    previous_status = order.status
    order.status = "executed"
    order.executed_at = now
    session.flush()
    session.add(
        AuditEvent(
            actor_id=actor_id,
            event_type=f"investment.{order.order_type}_executed",
            resource_type="investment_order",
            resource_id=order.id,
            resource_version=order.version,
            request_id=request_id,
            task_id=task_id,
            tool_execution_id=tool_execution_id,
            outcome="succeeded",
            before_state={"status": previous_status},
            after_state={
                "status": order.status,
                "amount_minor": order.amount_minor,
                "units_micros": order.units_micros,
            },
        )
    )
    return InvestmentOrderView(
        id=order.id,
        order_type=order.order_type,
        product_id=product.id,
        product_name=product.name,
        amount_minor=order.amount_minor,
        currency=order.currency,
        status=order.status,
        executed_at=_utc(order.executed_at),
        holding_id=order.holding_id,
    )


def _holding_view(holding: InvestmentHolding, product: InvestmentProduct) -> HoldingView:
    current_value = value_for_units(
        units_micros=holding.units_micros, unit_price_minor=product.unit_price_minor
    )
    cost_basis = value_for_units(
        units_micros=holding.units_micros, unit_price_minor=holding.purchase_price_minor
    )
    return HoldingView(
        id=holding.id,
        product_id=product.id,
        product_name=product.name,
        units_micros=holding.units_micros,
        purchase_price_minor=holding.purchase_price_minor,
        current_price_minor=product.unit_price_minor,
        current_value_minor=current_value,
        estimated_gain_minor=current_value - cost_basis,
        currency=product.currency,
        version=holding.version,
    )


def get_portfolio(session: Session, *, actor_id: UUID) -> PortfolioView:
    user = session.get(DemoUser, actor_id)
    if user is None:
        raise BankingRuleError("actor_not_found", "当前模拟用户不可用。")
    accounts = list(session.scalars(select(Account).where(Account.demo_user_id == actor_id)))
    cash = sum(account.balance_minor for account in accounts)
    rows = session.execute(
        select(InvestmentHolding, InvestmentProduct)
        .join(InvestmentProduct, InvestmentProduct.id == InvestmentHolding.product_id)
        .where(InvestmentHolding.actor_id == actor_id, InvestmentHolding.units_micros > 0)
        .order_by(InvestmentProduct.name, InvestmentHolding.purchased_at)
    )
    holdings = tuple(_holding_view(holding, product) for holding, product in rows)
    invested = sum(item.current_value_minor for item in holdings)
    gains = sum(item.estimated_gain_minor for item in holdings)
    currency = accounts[0].currency if accounts else "CNY"
    labels = {1: "保守型", 2: "稳健型", 3: "平衡型", 4: "成长型", 5: "进取型"}
    return PortfolioView(
        currency=currency,
        cash_balance_minor=cash,
        invested_value_minor=invested,
        estimated_gain_minor=gains,
        total_assets_minor=cash + invested,
        risk_level=user.risk_level,
        risk_label=labels[user.risk_level],
        holdings=holdings,
    )


def list_orders(
    session: Session, *, actor_id: UUID, limit: int = 50
) -> tuple[InvestmentOrderView, ...]:
    rows = session.execute(
        select(InvestmentOrder, InvestmentProduct)
        .join(InvestmentProduct, InvestmentProduct.id == InvestmentOrder.product_id)
        .where(InvestmentOrder.actor_id == actor_id)
        .order_by(InvestmentOrder.created_at.desc(), InvestmentOrder.id)
        .limit(limit)
    )
    return tuple(
        InvestmentOrderView(
            id=order.id,
            order_type=order.order_type,
            product_id=product.id,
            product_name=product.name,
            amount_minor=order.amount_minor,
            currency=order.currency,
            status=order.status,
            executed_at=_utc(order.executed_at),
            holding_id=order.holding_id,
        )
        for order, product in rows
    )
