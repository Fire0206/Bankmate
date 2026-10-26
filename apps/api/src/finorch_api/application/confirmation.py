import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from finorch_api.infrastructure.models import ConfirmationChallenge

CONFIRMATION_TTL = timedelta(minutes=5)


def parameters_hash(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_confirmation_challenge(
    session: Session,
    *,
    actor_id: UUID,
    task_id: UUID,
    tool_execution_id: UUID,
    tool_name: str,
    tool_version: str,
    idempotency_key: str,
    policy_version: str,
    parameters_digest: str,
    target_status: str,
    resource_type: str,
    resource_id: UUID,
    resource_version: int,
) -> ConfirmationChallenge:
    resource_fields: dict[str, object] = {
        "card_id": None,
        "card_application_id": None,
        "birthday_plan_id": None,
        "birthday_order_id": None,
        "subscription_id": None,
        "transfer_id": None,
        "split_bill_id": None,
        "investment_order_id": None,
        "card_version": None,
        "card_application_version": None,
        "birthday_plan_version": None,
        "birthday_order_version": None,
        "subscription_version": None,
        "transfer_version": None,
        "split_bill_version": None,
        "investment_order_version": None,
    }
    resource_columns = {
        "card": ("card_id", "card_version"),
        "card_application": ("card_application_id", "card_application_version"),
        "birthday_plan": ("birthday_plan_id", "birthday_plan_version"),
        "birthday_order": ("birthday_order_id", "birthday_order_version"),
        "subscription": ("subscription_id", "subscription_version"),
        "transfer": ("transfer_id", "transfer_version"),
        "split": ("split_bill_id", "split_bill_version"),
        "investment_order": ("investment_order_id", "investment_order_version"),
    }
    try:
        id_field, version_field = resource_columns[resource_type]
    except KeyError as exc:
        raise ValueError("Unsupported confirmation resource type.") from exc
    resource_fields[id_field] = resource_id
    resource_fields[version_field] = resource_version
    challenge = ConfirmationChallenge(
        id=uuid4(),
        task_id=task_id,
        tool_execution_id=tool_execution_id,
        actor_id=actor_id,
        tool_name=tool_name,
        tool_version=tool_version,
        target_status=target_status,
        parameters_hash=parameters_digest,
        policy_version=policy_version,
        idempotency_key=idempotency_key,
        status="pending",
        expires_at=datetime.now(UTC) + CONFIRMATION_TTL,
        **resource_fields,
    )
    session.add(challenge)
    session.flush()
    return challenge
