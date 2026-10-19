from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from finorch_api.application.bills import get_month_anomalies, get_monthly_summary
from finorch_api.application.subscriptions import list_subscriptions


@dataclass(frozen=True)
class FinancialRecommendationView:
    id: str
    category: str
    priority: str
    title: str
    explanation: str
    amount_minor: int | None
    currency: str
    source_transaction_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class FinancialRecommendationsView:
    month: str
    generated_at: datetime
    items: tuple[FinancialRecommendationView, ...]


def get_financial_recommendations(
    session: Session, *, actor_id: UUID, month: str | None = None
) -> FinancialRecommendationsView:
    """Return on-demand, deterministic observations from the actor's synthetic data."""
    summary = get_monthly_summary(session, actor_id=actor_id, month=month)
    anomalies = get_month_anomalies(session, actor_id=actor_id, month=summary.month)
    subscriptions = list_subscriptions(session, actor_id=actor_id)
    recommendations: list[FinancialRecommendationView] = []

    duplicate_charges = tuple(
        item
        for item in anomalies
        if item.anomaly_reason is not None and "重复扣费提示" in item.anomaly_reason
    )
    if duplicate_charges:
        recommendations.append(
            FinancialRecommendationView(
                id="review_duplicate_charge",
                category="bill_review",
                priority="high",
                title="核对重复扣费记录",
                explanation=(
                    "账单规则发现同一账户、商户和 UTC 日期存在重复记录。"
                    "这只是核对提示，不代表已判定为欺诈。"
                ),
                amount_minor=max(item.amount_minor for item in duplicate_charges),
                currency="CNY",
                source_transaction_ids=tuple(item.id for item in duplicate_charges),
            )
        )

    if summary.net_minor < 0:
        recommendations.append(
            FinancialRecommendationView(
                id="review_monthly_cashflow",
                category="cashflow_review",
                priority="medium",
                title="本月支出高于收入",
                explanation=(
                    f"{summary.month} 的合成流水显示支出高于收入；"
                    "可先检查较大的支出类别，再决定是否调整计划。"
                ),
                amount_minor=abs(summary.net_minor),
                currency=summary.currency,
                source_transaction_ids=(),
            )
        )

    if subscriptions.monthly_total_minor > 0:
        recommendations.append(
            FinancialRecommendationView(
                id="review_recurring_expenses",
                category="subscription_review",
                priority="low",
                title="查看自动续费支出",
                explanation=(
                    "当前有处于启用状态的月度订阅。可核对服务是否仍在使用；"
                    "系统没有使用行为数据，不会据此判断订阅是否浪费。"
                ),
                amount_minor=subscriptions.monthly_total_minor,
                currency=subscriptions.currency,
                source_transaction_ids=(),
            )
        )

    return FinancialRecommendationsView(
        month=summary.month,
        generated_at=datetime.now(UTC),
        items=tuple(recommendations),
    )
