from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import URL

from alembic import command
from bankmate_api.agent.providers import ProviderSelection
from bankmate_api.agent.runtime import FakeProvider
from bankmate_api.api.v1.agent import get_provider_selection
from bankmate_api.domain.risk_assessment import score_risk
from bankmate_api.infrastructure.database import build_engine, get_db_session
from bankmate_api.infrastructure.models import AuditEvent, DemoUser, InvestmentOrder, RiskAssessment
from bankmate_api.main import app
from bankmate_api.reset import reset_demo_data
from bankmate_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DEMO_USER_TWO_ID,
    DemoActor,
    get_current_demo_actor,
)
from bankmate_api.seed_data import seed_demo_data

QUESTIONNAIRE = "/api/v1/investments/risk-assessment"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def assessment_api(seeded_database):
    actor = [DEMO_USER_ONE_ID]

    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(actor[0])
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        FakeProvider(), "fake"
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, actor, seeded_database
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)
        app.dependency_overrides.pop(get_provider_selection, None)


def answers(level: int) -> dict[str, int | str]:
    return {
        "questionnaire_version": "demo-risk-v1",
        "time_horizon": level,
        "loss_tolerance": level,
        "liquidity_capacity": level,
        "investment_experience": level,
    }


def test_questionnaire_is_read_only_and_agent_cannot_answer_for_user(assessment_api) -> None:
    client, _actor, database = assessment_api
    form = client.get(f"{QUESTIONNAIRE}/questionnaire")
    assert form.status_code == 200
    assert len(form.json()["questions"]) == 4
    assert all(len(item["options"]) == 5 for item in form.json()["questions"])

    task = client.post(
        "/api/v1/agent/tasks",
        json={"request_text": "我想做风险测评"},
        headers={"Idempotency-Key": "risk-form-task"},
    )
    assert task.status_code == 200, task.text
    assert task.json()["status"] == "completed"
    assert any(
        step["tool_name"] == "investment.assessment_questions" for step in task.json()["steps"]
    )
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 0


def test_loss_tolerance_and_liquidity_cap_the_score() -> None:
    assert score_risk(
        {
            "time_horizon": 5,
            "loss_tolerance": 1,
            "liquidity_capacity": 5,
            "investment_experience": 5,
        }
    ) == (16, 1)
    assert score_risk(
        {
            "time_horizon": 5,
            "loss_tolerance": 5,
            "liquidity_capacity": 1,
            "investment_experience": 5,
        }
    ) == (16, 1)


def test_submit_is_scored_audited_idempotent_and_seed_preserves_profile(assessment_api) -> None:
    client, actor, database = assessment_api
    initial = client.get("/api/v1/investments/profile").json()["risk_level"]
    assert initial == 3
    response = client.post(QUESTIONNAIRE, json=answers(1), headers={"Idempotency-Key": "risk-low"})
    assert response.status_code == 200, response.text
    assert response.json()["score"] == 4
    assert response.json()["risk_level"] == 1
    assert response.json()["assessed_at"].endswith("Z")
    assert client.get("/api/v1/investments/profile").json()["risk_level"] == 1
    latest = client.get(f"{QUESTIONNAIRE}/latest").json()
    assert latest["id"] == response.json()["id"]
    assert latest["assessed_at"] == response.json()["assessed_at"]
    assert (
        client.post(QUESTIONNAIRE, json=answers(1), headers={"Idempotency-Key": "risk-low"}).json()[
            "id"
        ]
        == response.json()["id"]
    )
    conflict = client.post(QUESTIONNAIRE, json=answers(5), headers={"Idempotency-Key": "risk-low"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    with database.session_factory.begin() as session:
        seed_demo_data(session)
    with database.session_factory() as session:
        assert session.get(DemoUser, actor[0]).risk_level == 1
        assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 1
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "investment.risk_assessed")
        )
        assert event is not None
        assert event.before_state == {"risk_level": 3}
        assert event.after_state["risk_level"] == 1


def test_assessment_is_actor_scoped_and_bad_answers_do_not_change_profile(assessment_api) -> None:
    client, actor, database = assessment_api
    assert (
        client.post(
            QUESTIONNAIRE, json=answers(1), headers={"Idempotency-Key": "same-key"}
        ).status_code
        == 200
    )
    actor[0] = DEMO_USER_TWO_ID
    assert client.get(f"{QUESTIONNAIRE}/latest").json() is None
    assert client.get("/api/v1/investments/profile").json()["risk_level"] == 1
    assert (
        client.post(
            QUESTIONNAIRE, json=answers(5), headers={"Idempotency-Key": "same-key"}
        ).status_code
        == 200
    )
    bad = client.post(
        QUESTIONNAIRE,
        json={**answers(1), "loss_tolerance": 6},
        headers={"Idempotency-Key": "bad-answer"},
    )
    assert bad.status_code == 422
    with database.session_factory() as session:
        assert session.get(DemoUser, DEMO_USER_ONE_ID).risk_level == 1
        assert session.get(DemoUser, DEMO_USER_TWO_ID).risk_level == 5
        assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 2


def test_explicit_reset_clears_assessment_and_restores_seeded_profile(assessment_api) -> None:
    client, _actor, database = assessment_api
    assert (
        client.post(
            QUESTIONNAIRE, json=answers(1), headers={"Idempotency-Key": "reset-risk"}
        ).status_code
        == 200
    )
    with database.session_factory.begin() as session:
        reset_demo_data(session)
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 0
        assert session.get(DemoUser, DEMO_USER_ONE_ID).risk_level == 3


def test_pending_purchase_rechecks_suitability_after_downgrade(assessment_api) -> None:
    client, _actor, database = assessment_api
    task_response = client.post(
        "/api/v1/agent/tasks",
        json={"request_text": "申购 1000 元稳健短债组合"},
        headers={"Idempotency-Key": "pending-purchase-risk"},
    )
    assert task_response.status_code == 200, task_response.text
    task = task_response.json()
    assert task["status"] == "awaiting_confirmation", task
    assert (
        client.post(
            QUESTIONNAIRE, json=answers(1), headers={"Idempotency-Key": "downgrade-risk"}
        ).status_code
        == 200
    )
    challenge = task["confirmation"]
    confirmation = client.post(
        f"/api/v1/agent/tasks/{task['id']}/confirm",
        json={"challenge_id": challenge["id"], "parameters_hash": challenge["parameters_hash"]},
        headers={"Idempotency-Key": challenge["idempotency_key"]},
    )
    assert confirmation.status_code in {200, 409}, confirmation.text
    if confirmation.status_code == 200:
        assert confirmation.json()["status"] != "completed"
    with database.session_factory() as session:
        orders = list(
            session.scalars(
                select(InvestmentOrder).where(InvestmentOrder.actor_id == DEMO_USER_ONE_ID)
            )
        )
        assert len(orders) == 1
        assert orders[0].status != "executed"


def test_migration_preserves_previous_user_risk_level(tmp_path: Path) -> None:
    path = tmp_path / "risk-assessment-migration.sqlite3"
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.attributes["database_url"] = url
    engine = build_engine(url)
    try:
        command.upgrade(config, "0007_transfer_phone_remark")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO demo_users "
                    "(id, display_name, dataset_version, risk_level, created_at) "
                    "VALUES ('00000000000040008000000000000001', 'Prior Demo', "
                    "'phase3-v1', 4, '2026-10-01')"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT risk_level FROM demo_users")) == 4
            assert connection.scalar(text("SELECT count(*) FROM risk_assessments")) == 0
    finally:
        engine.dispose()
