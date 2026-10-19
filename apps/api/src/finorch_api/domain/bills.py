import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

ANOMALY_AMOUNT_THRESHOLD_MINOR = 100_000


class TransactionLike(Protocol):
    id: object
    account_id: object
    direction: str
    amount_minor: int
    currency: str
    merchant: str
    occurred_at: datetime


@dataclass(frozen=True)
class TransactionAnomaly:
    transaction_id: str
    reason: str


def detect_anomaly(transaction: TransactionLike) -> str | None:
    """Apply the published deterministic demo rule; this is not fraud detection."""
    if (
        transaction.direction == "expense"
        and transaction.category != "住房"
        and transaction.amount_minor >= ANOMALY_AMOUNT_THRESHOLD_MINOR
    ):
        return "非住房单笔支出达到演示提示阈值 ¥1,000。"
    return None


def detect_anomaly_reasons(transactions: Iterable[TransactionLike]) -> dict[object, str]:
    """Return explainable amount and repeated-charge notices, never fraud verdicts."""
    rows = list(transactions)
    reasons: dict[object, list[str]] = {}
    duplicate_groups: dict[tuple[object, str, int, str, str], list[TransactionLike]] = {}

    for transaction in rows:
        amount_reason = detect_anomaly(transaction)
        if amount_reason:
            reasons.setdefault(transaction.id, []).append(amount_reason)
        if transaction.direction != "expense":
            continue
        occurred_at = transaction.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        else:
            occurred_at = occurred_at.astimezone(UTC)
        merchant = re.sub(r"\s+", " ", transaction.merchant).strip().casefold()
        duplicate_key = (
            transaction.account_id,
            merchant,
            transaction.amount_minor,
            transaction.currency,
            occurred_at.date().isoformat(),
        )
        duplicate_groups.setdefault(duplicate_key, []).append(transaction)

    duplicate_reason = (
        "同一账户同一商户在同一天出现多笔相同金额扣款；这是重复扣费提示，不代表欺诈。"
    )
    for duplicates in duplicate_groups.values():
        if len(duplicates) < 2:
            continue
        for transaction in duplicates:
            reasons.setdefault(transaction.id, []).append(duplicate_reason)

    return {transaction_id: "；".join(values) for transaction_id, values in reasons.items()}
