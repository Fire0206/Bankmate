"""User-submitted synthetic risk assessments; the model never supplies answers."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankmate_api.application.errors import BankingRuleError
from bankmate_api.application.transactions import write_transaction
from bankmate_api.domain.risk_assessment import (
    QUESTIONNAIRE_VERSION,
    QUESTIONS,
    RiskAnswers,
    score_risk,
)
from bankmate_api.infrastructure.models import AuditEvent, DemoUser, RiskAssessment, utc_now


class AssessmentIdempotencyConflictError(RuntimeError):
    """The same actor/key was used for a different questionnaire response."""


@dataclass(frozen=True)
class AssessmentView:
    id: UUID
    questionnaire_version: str
    score: int
    risk_level: int
    risk_label: str
    assessed_at: datetime


RISK_LABELS = {1: "保守型", 2: "稳健型", 3: "平衡型", 4: "成长型", 5: "进取型"}


def questionnaire_data() -> dict[str, object]:
    return {
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "questions": [
            {
                "key": question["key"],
                "title": question["title"],
                "options": [
                    {"value": index, "label": label}
                    for index, label in enumerate(question["options"], start=1)
                ],
            }
            for question in QUESTIONS
        ],
        "notice": (
            "仅用于合成数据演示。请本人如实作答；模型不能代答，测评不代表真实银行适当性评估。"
        ),
    }


def _view(row: RiskAssessment) -> AssessmentView:
    return AssessmentView(
        id=row.id,
        questionnaire_version=row.questionnaire_version,
        score=row.score,
        risk_level=row.risk_level,
        risk_label=RISK_LABELS[row.risk_level],
        assessed_at=(
            row.created_at.replace(tzinfo=UTC)
            if row.created_at.tzinfo is None
            else row.created_at.astimezone(UTC)
        ),
    )


def latest_assessment(session: Session, *, actor_id: UUID) -> AssessmentView | None:
    row = session.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.actor_id == actor_id)
        .order_by(RiskAssessment.created_at.desc(), RiskAssessment.id.desc())
        .limit(1)
    )
    return _view(row) if row is not None else None


def submit_assessment(
    session: Session,
    *,
    actor_id: UUID,
    answers: RiskAnswers,
    idempotency_key: str,
    request_id: str,
) -> AssessmentView:
    canonical = json.dumps(answers, sort_keys=True, separators=(",", ":"))
    answers_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    score, risk_level = score_risk(answers)
    with write_transaction(session, immediate=True):
        existing = session.scalar(
            select(RiskAssessment).where(
                RiskAssessment.actor_id == actor_id,
                RiskAssessment.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.answers_hash != answers_hash:
                raise AssessmentIdempotencyConflictError
            return _view(existing)
        user = session.get(DemoUser, actor_id)
        if user is None:
            raise BankingRuleError("actor_not_found", "当前模拟用户不可用。")
        before_level = user.risk_level
        now = utc_now()
        row = RiskAssessment(
            id=uuid4(),
            actor_id=actor_id,
            questionnaire_version=QUESTIONNAIRE_VERSION,
            answers=dict(answers),
            answers_hash=answers_hash,
            score=score,
            risk_level=risk_level,
            idempotency_key=idempotency_key,
            created_at=now,
        )
        session.add(row)
        user.risk_level = risk_level
        session.add(
            AuditEvent(
                id=uuid4(),
                actor_id=actor_id,
                card_id=None,
                event_type="investment.risk_assessed",
                resource_type="risk_assessment",
                resource_id=row.id,
                request_id=request_id,
                task_id=None,
                tool_execution_id=None,
                outcome="succeeded",
                before_state={"risk_level": before_level},
                after_state={
                    "risk_level": risk_level,
                    "questionnaire_version": QUESTIONNAIRE_VERSION,
                },
                occurred_at=now,
            )
        )
        session.flush()
        return _view(row)
