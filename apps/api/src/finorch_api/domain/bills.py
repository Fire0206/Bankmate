from dataclasses import dataclass
from typing import Protocol

ANOMALY_AMOUNT_THRESHOLD_MINOR = 100_000


class TransactionLike(Protocol):
    direction: str
    amount_minor: int


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
