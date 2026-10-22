"""Deterministic risk decisions. Call inside the serialized write UoW at execution.

This module never authorizes a write itself: ownership, resource versions, funds,
suitability, explicit confirmation and any required verification remain gates.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finorch_api.infrastructure.models import Transfer

POLICY_VERSION = "risk-v1"
DAILY_TRANSFER_LIMIT_MINOR = 100_000
BUSINESS_TIMEZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class RiskDecision:
    level: Literal["green", "yellow", "red"]
    confirmation_method: Literal["none", "explicit", "demo_otp"]
    rules: tuple[str, ...]
    policy_version: str = POLICY_VERSION


def business_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        raise ValueError("Risk decisions require an aware timestamp.")
    start = now.astimezone(BUSINESS_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def executed_transfer_total(session: Session, *, actor_id: UUID, now: datetime) -> int:
    """Sum executed debits, across all actor accounts, for the UTC+8 business day.

    Scheduled proposals do not count until executed. Retries do not create another
    transfer row. Callers must take BEGIN IMMEDIATE before deciding and writing.
    """
    start, end = business_day_bounds(now)
    return int(
        session.scalar(
            select(func.coalesce(func.sum(Transfer.amount_minor), 0)).where(
                Transfer.actor_id == actor_id,
                Transfer.status == "executed",
                Transfer.currency == "CNY",
                Transfer.executed_at >= start,
                Transfer.executed_at < end,
            )
        )
        or 0
    )


def decide_risk(
    *,
    operation: Literal["read", "transfer", "investment_buy", "write", "sensitive_card"],
    amount_minor: int = 0,
    daily_executed_minor: int = 0,
    currency: str = "CNY",
    product_risk: int | None = None,
    high_risk_signal: bool = False,
) -> RiskDecision:
    if type(amount_minor) is not int or type(daily_executed_minor) is not int:
        raise ValueError("Risk amounts must be integer minor units.")
    if amount_minor < 0 or daily_executed_minor < 0:
        raise ValueError("Risk amounts cannot be negative.")
    if operation not in {"read", "transfer", "investment_buy", "write", "sensitive_card"}:
        raise ValueError("Unknown risk operation.")
    if operation == "read":
        return RiskDecision("green", "none", ("owned_read_only",))
    rules = []
    if high_risk_signal:
        rules.append("high_risk_signal")
    if operation == "sensitive_card":
        rules.append("sensitive_card_change")
    if operation == "transfer":
        if currency != "CNY":
            raise ValueError("Transfer risk policy supports CNY only.")
        if amount_minor <= 0:
            raise ValueError("Transfer amount must be positive.")
        if daily_executed_minor + amount_minor > DAILY_TRANSFER_LIMIT_MINOR:
            rules.append("daily_transfer_above_1000_cny")
    if operation == "investment_buy":
        if type(product_risk) is not int or product_risk not in range(1, 6):
            raise ValueError("Investment risk level must be known.")
        if product_risk >= 4:
            rules.append("high_risk_investment")
    if rules:
        return RiskDecision("red", "demo_otp", tuple(rules))
    return RiskDecision("yellow", "explicit", ("explicit_business_confirmation",))
