from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bankmate_api.application.handoffs import (
    HandoffStateError,
    create_failure_handoff_if_needed,
    simulate_operator_update,
)
from bankmate_api.infrastructure.database import get_db_session
from bankmate_api.infrastructure.models import (
    AgentTask,
    AuditEvent,
    HumanHandoff,
    TaskStep,
    ToolExecution,
)
from bankmate_api.main import app
from bankmate_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DEMO_USER_TWO_ID,
    DemoActor,
    get_current_demo_actor,
)


def test_actor_scoped_handoff_and_local_operator(seeded_database) -> None:
    actor = [DEMO_USER_ONE_ID]

    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(actor[0])
    try:
        with seeded_database.session_factory.begin() as session:
            task = AgentTask(
                actor_id=DEMO_USER_ONE_ID,
                conversation_id=UUID("30000000-0000-4000-8000-000000000001"),
                idempotency_key="handoff-test",
                request_hash="a" * 64,
                request_text="测试任务",
                provider_mode="fake",
                status="failed",
                message="无法继续",
                error_code="test_error",
            )
            session.add(task)
            session.flush()
            task_id = task.id
        with TestClient(app) as client:
            path = f"/api/v1/agent/tasks/{task_id}/handoff"
            assert client.get(path).json() is None
            created = client.post(path, json={"reason": "cannot_continue"})
            assert created.status_code == 200, created.text
            ticket = created.json()
            assert ticket["status"] == "pending"
            assert ticket["completed_tools"] == []
            assert (
                client.post(path, json={"reason": "cannot_continue"}).json()["id"] == ticket["id"]
            )
            actor[0] = DEMO_USER_TWO_ID
            assert client.get(path).json() is None
            assert client.post(path, json={"reason": "user_requested"}).status_code == 404
            actor[0] = DEMO_USER_ONE_ID
            with seeded_database.session_factory() as session:
                started = simulate_operator_update(
                    session,
                    ticket_id=UUID(ticket["id"]),
                    target_status="in_progress",
                    outcome=None,
                    request_id="test-operator",
                )
                assert started.status == "in_progress"
                with pytest.raises(HandoffStateError):
                    simulate_operator_update(
                        session,
                        ticket_id=UUID(ticket["id"]),
                        target_status="resolved",
                        outcome=None,
                        request_id="test-operator",
                    )
                resolved = simulate_operator_update(
                    session,
                    ticket_id=UUID(ticket["id"]),
                    target_status="resolved",
                    outcome="已解释处理结果；未执行资金操作。",
                    request_id="test-operator",
                )
                assert resolved.status == "resolved"
            assert client.get(path).json()["status"] == "resolved"
            with seeded_database.session_factory() as session:
                assert session.scalar(select(func.count()).select_from(HumanHandoff)) == 1
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.resource_type == "human_handoff")
                    )
                    == 3
                )
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)


def test_failed_partial_write_triggers_one_advisory_handoff(seeded_database) -> None:
    with seeded_database.session_factory.begin() as session:
        task = AgentTask(
            actor_id=DEMO_USER_ONE_ID,
            conversation_id=UUID("30000000-0000-4000-8000-000000000001"),
            idempotency_key="partial-handoff-task",
            request_hash="b" * 64,
            request_text="模拟跨场景任务",
            provider_mode="fake",
            status="failed",
            message="后续步骤未能完成",
            error_code="agent_workflow_incomplete",
        )
        session.add(task)
        session.flush()
        step = TaskStep(
            task_id=task.id,
            sequence=1,
            step_type="tool",
            status="succeeded",
            summary="第一笔已确认操作",
        )
        session.add(step)
        session.flush()
        session.add(
            ToolExecution(
                task_id=task.id,
                step_id=step.id,
                actor_id=DEMO_USER_ONE_ID,
                tool_name="card.freeze",
                tool_version="1.0",
                idempotency_key="partial-card-freeze",
                input_hash="c" * 64,
                status="succeeded",
                result_summary="Card was frozen.",
            )
        )
        task_id = task.id

    with seeded_database.session_factory() as session:
        first = create_failure_handoff_if_needed(
            session,
            actor_id=DEMO_USER_ONE_ID,
            task_id=task_id,
            request_id="partial-handoff",
        )
        second = create_failure_handoff_if_needed(
            session,
            actor_id=DEMO_USER_ONE_ID,
            task_id=task_id,
            request_id="partial-handoff-retry",
        )
        assert first is not None
        assert first.reason == "partial_success"
        assert first.id == second.id
        assert first.completed_tools == ("card.freeze",)

    with seeded_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(HumanHandoff)) == 1
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "handoff.requested")
        )
        assert event is not None
        assert event.after_state == {
            "status": "pending",
            "reason": "partial_success",
            "trigger": "automatic_failure",
        }


def test_deterministic_rejection_does_not_auto_create_handoff(seeded_database) -> None:
    with seeded_database.session_factory.begin() as session:
        task = AgentTask(
            actor_id=DEMO_USER_ONE_ID,
            conversation_id=UUID("30000000-0000-4000-8000-000000000001"),
            idempotency_key="deterministic-rejection",
            request_hash="d" * 64,
            request_text="风险不匹配请求",
            provider_mode="fake",
            status="failed",
            message="产品不符合风险等级",
            error_code="risk_mismatch",
        )
        session.add(task)
        session.flush()
        task_id = task.id

    with seeded_database.session_factory() as session:
        assert (
            create_failure_handoff_if_needed(
                session,
                actor_id=DEMO_USER_ONE_ID,
                task_id=task_id,
                request_id="risk-rejection",
            )
            is None
        )
        assert session.scalar(select(func.count()).select_from(HumanHandoff)) == 0
