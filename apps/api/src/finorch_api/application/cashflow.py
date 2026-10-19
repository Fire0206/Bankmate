from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from finorch_api.application.bills import get_monthly_summary
from finorch_api.application.errors import BankingRuleError
from finorch_api.application.transfers import list_accounts


@dataclass(frozen=True)
class PaydayPlanView:
    account_label: str
    currency: str
    month: str
    account_balance_minor: int
    monthly_income_minor: int
    monthly_expense_minor: int
    recipient_name: str
    transfer_amount_minor: int
    reserve_amount_minor: int
    remaining_after_transfer_minor: int
    investment_budget_minor: int
    reserve_shortfall_minor: int


def plan_payday_allocation(
    session: Session,
    *,
    actor_id: UUID,
    recipient_name: str,
    transfer_amount_minor: int,
    reserve_amount_minor: int,
    source_account_label: str | None = None,
    month: str | None = None,
) -> PaydayPlanView:
    accounts = list_accounts(session, actor_id=actor_id)
    if source_account_label:
        normalized = source_account_label.strip().casefold()
        account = next((item for item in accounts if item.label.casefold() == normalized), None)
        if account is None:
            raise BankingRuleError("account_not_found", "没有找到当前模拟用户的指定账户。")
    else:
        account = next(iter(accounts), None)
    if account is None:
        raise BankingRuleError("account_not_found", "当前模拟用户没有可用账户。")
    if account.currency != "CNY":
        raise BankingRuleError("unsupported_currency", "当前演示计划仅支持人民币账户。")

    summary = get_monthly_summary(session, actor_id=actor_id, month=month)
    remaining = account.balance_minor - transfer_amount_minor
    investment_budget = max(0, remaining - reserve_amount_minor)
    reserve_shortfall = max(0, reserve_amount_minor - remaining)
    return PaydayPlanView(
        account_label=account.label,
        currency=account.currency,
        month=summary.month,
        account_balance_minor=account.balance_minor,
        monthly_income_minor=summary.income_minor,
        monthly_expense_minor=summary.expense_minor,
        recipient_name=recipient_name.strip(),
        transfer_amount_minor=transfer_amount_minor,
        reserve_amount_minor=reserve_amount_minor,
        remaining_after_transfer_minor=remaining,
        investment_budget_minor=investment_budget,
        reserve_shortfall_minor=reserve_shortfall,
    )
