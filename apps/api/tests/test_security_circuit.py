from datetime import timedelta
from uuid import uuid4

from bankmate_api.agent.providers import ProviderSelection
from bankmate_api.agent.runtime import FakeProvider
from bankmate_api.application.agent import create_agent_task
from bankmate_api.application.transactions import write_transaction
from bankmate_api.infrastructure.models import AuditEvent, utc_now
from bankmate_api.security.circuit import (
    HOLD_DURATION,
    active_write_hold,
    record_safety_signal,
)
from bankmate_api.security.demo_identity import DEMO_USER_ONE_ID, DEMO_USER_TWO_ID
from sqlalchemy import func, select


def test_circuit_is_short_lived_actor_scoped_and_audited(seeded_database) -> None:
    with seeded_database.session_factory() as session:
        task = create_agent_task(
            session,
            actor_id=DEMO_USER_ONE_ID,
            request_text="查看我的银行卡",
            conversation_id=uuid4(),
            idempotency_key="circuit-unit",
            request_id="test",
            selection=ProviderSelection(FakeProvider(), "fake"),
        )
    now = utc_now()
    with seeded_database.session_factory() as session:
        with write_transaction(session, immediate=True):
            for index in range(3):
                deadline = record_safety_signal(
                    session,
                    actor_id=DEMO_USER_ONE_ID,
                    code="tool_input_invalid",
                    request_id=f"signal-{index}",
                    task_id=task.id,
                    now=now + timedelta(seconds=index),
                )
                assert (deadline is not None) is (index == 2)
    with seeded_database.session_factory() as session:
        deadline = active_write_hold(session, actor_id=DEMO_USER_ONE_ID, now=now)
        assert deadline is not None and deadline <= now + HOLD_DURATION + timedelta(seconds=3)
        assert active_write_hold(session, actor_id=DEMO_USER_TWO_ID, now=now) is None
        assert (
            active_write_hold(session, actor_id=DEMO_USER_ONE_ID, now=now + timedelta(minutes=3))
            is None
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "security.write_hold_started")
            )
            == 1
        )
