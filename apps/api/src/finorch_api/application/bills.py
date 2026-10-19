from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch_api.domain.bills import detect_anomaly
from finorch_api.infrastructure.models import Account, Transaction


@dataclass(frozen=True)
class TransactionView:
    id: UUID
    account_id: UUID
    direction: str
    amount_minor: int
    currency: str
    merchant: str
    category: str
    description: str
    occurred_at: datetime
    anomaly_reason: str | None


@dataclass(frozen=True)
class TransactionPage:
    items: tuple[TransactionView, ...]
    total: int
    offset: int
    limit: int
    next_offset: int | None


@dataclass(frozen=True)
class CategorySpendView:
    category: str
    amount_minor: int
    transaction_count: int


@dataclass(frozen=True)
class MonthlyTrendView:
    month: str
    income_minor: int
    expense_minor: int


@dataclass(frozen=True)
class BillSummaryView:
    month: str
    currency: str
    income_minor: int
    expense_minor: int
    net_minor: int
    selected_category: str | None
    selected_category_expense_minor: int | None
    categories: tuple[CategorySpendView, ...]
    trends: tuple[MonthlyTrendView, ...]
    anomalies: tuple[TransactionView, ...]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _month_start(month: str | None) -> date:
    if month is None:
        return datetime.now(UTC).date().replace(day=1)
    try:
        parsed = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise ValueError("Month must use YYYY-MM format.") from exc
    if parsed.strftime("%Y-%m") != month:
        raise ValueError("Month must use YYYY-MM format.")
    return parsed


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def _view(transaction: Transaction) -> TransactionView:
    return TransactionView(
        id=transaction.id,
        account_id=transaction.account_id,
        direction=transaction.direction,
        amount_minor=transaction.amount_minor,
        currency=transaction.currency,
        merchant=transaction.merchant,
        category=transaction.category,
        description=transaction.description,
        occurred_at=_utc(transaction.occurred_at),
        anomaly_reason=detect_anomaly(transaction),
    )


def _owned_transactions(
    session: Session,
    *,
    actor_id: UUID,
    start: datetime,
    end: datetime,
    category: str | None = None,
    merchant: str | None = None,
    direction: str | None = None,
) -> list[Transaction]:
    statement = (
        select(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .where(
            Account.demo_user_id == actor_id,
            Transaction.entry_kind == "bill",
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
        )
    )
    if category:
        statement = statement.where(Transaction.category == category.strip())
    if merchant:
        statement = statement.where(Transaction.merchant.ilike(f"%{merchant.strip()}%"))
    if direction:
        statement = statement.where(Transaction.direction == direction)
    return list(session.scalars(statement.order_by(Transaction.occurred_at.desc(), Transaction.id)))


def list_transactions(
    session: Session,
    *,
    actor_id: UUID,
    month: str | None = None,
    category: str | None = None,
    merchant: str | None = None,
    direction: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> TransactionPage:
    month_start = _month_start(month)
    start = datetime.combine(month_start, time.min, tzinfo=UTC)
    end = datetime.combine(_next_month(month_start), time.min, tzinfo=UTC)
    rows = _owned_transactions(
        session,
        actor_id=actor_id,
        start=start,
        end=end,
        category=category,
        merchant=merchant,
        direction=direction,
    )
    page = rows[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(rows) else None
    return TransactionPage(
        items=tuple(_view(row) for row in page),
        total=len(rows),
        offset=offset,
        limit=limit,
        next_offset=next_offset,
    )


def get_monthly_summary(
    session: Session,
    *,
    actor_id: UUID,
    month: str | None = None,
    category: str | None = None,
) -> BillSummaryView:
    selected_month = _month_start(month)
    month_label = selected_month.strftime("%Y-%m")
    start = datetime.combine(selected_month, time.min, tzinfo=UTC)
    end = datetime.combine(_next_month(selected_month), time.min, tzinfo=UTC)
    rows = _owned_transactions(session, actor_id=actor_id, start=start, end=end)
    income = sum(item.amount_minor for item in rows if item.direction == "income")
    expense = sum(item.amount_minor for item in rows if item.direction == "expense")
    category_totals: dict[str, list[int]] = {}
    for item in rows:
        if item.direction == "expense":
            values = category_totals.setdefault(item.category, [0, 0])
            values[0] += item.amount_minor
            values[1] += 1
    categories = tuple(
        CategorySpendView(category=name, amount_minor=values[0], transaction_count=values[1])
        for name, values in sorted(category_totals.items(), key=lambda pair: (-pair[1][0], pair[0]))
    )
    selected_total = (
        sum(
            item.amount_minor
            for item in rows
            if item.direction == "expense" and item.category == category
        )
        if category
        else None
    )

    trend_months: list[date] = [selected_month]
    for _ in range(5):
        trend_months.append(_previous_month(trend_months[-1]))
    trend_rows = _owned_transactions(
        session,
        actor_id=actor_id,
        start=datetime.combine(trend_months[-1], time.min, tzinfo=UTC),
        end=end,
    )
    trend_values: dict[str, list[int]] = {value.strftime("%Y-%m"): [0, 0] for value in trend_months}
    for item in trend_rows:
        label = _utc(item.occurred_at).strftime("%Y-%m")
        totals = trend_values.get(label)
        if totals is not None:
            totals[0 if item.direction == "income" else 1] += item.amount_minor
    trends = tuple(
        MonthlyTrendView(month=label, income_minor=values[0], expense_minor=values[1])
        for label, values in sorted(trend_values.items())
    )

    return BillSummaryView(
        month=month_label,
        currency="CNY",
        income_minor=income,
        expense_minor=expense,
        net_minor=income - expense,
        selected_category=category,
        selected_category_expense_minor=selected_total,
        categories=categories,
        trends=trends,
        anomalies=tuple(_view(item) for item in rows if detect_anomaly(item)),
    )


def get_month_anomalies(
    session: Session, *, actor_id: UUID, month: str | None = None
) -> tuple[TransactionView, ...]:
    selected_month = _month_start(month)
    rows = _owned_transactions(
        session,
        actor_id=actor_id,
        start=datetime.combine(selected_month, time.min, tzinfo=UTC),
        end=datetime.combine(_next_month(selected_month), time.min, tzinfo=UTC),
    )
    return tuple(_view(item) for item in rows if detect_anomaly(item))
