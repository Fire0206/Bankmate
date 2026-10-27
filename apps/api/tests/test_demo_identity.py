from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from finorch_api.config import Settings, get_settings
from finorch_api.infrastructure.database import get_db_session
from finorch_api.main import app
from finorch_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DemoActor,
    get_current_demo_actor,
)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_demo_identity_uses_server_selected_user(environment: str) -> None:
    selected_user = UUID("00000000-0000-4000-8000-000000000002")

    actor = get_current_demo_actor(Settings(environment=environment, demo_user_id=selected_user))

    assert actor.user_id == selected_user


def test_demo_identity_is_disabled_in_production() -> None:
    with pytest.raises(HTTPException) as error:
        get_current_demo_actor(Settings(environment="production"))

    assert error.value.status_code == 503
    assert error.value.detail == "Demo identity is unavailable."


def test_default_demo_identity_is_a_synthetic_user() -> None:
    assert Settings().demo_user_id == DEMO_USER_ONE_ID


@pytest.mark.parametrize(
    ("provider", "egress_enabled", "expected"),
    [
        ("fake", True, False),
        ("openai-compatible", False, False),
        ("openai-compatible", True, True),
    ],
)
def test_demo_session_reports_external_model_egress_state(
    seeded_database, provider: str, egress_enabled: bool, expected: bool
) -> None:
    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    settings = Settings(
        _env_file=None,
        environment="development",
        agent_provider=provider,
        llm_data_egress_enabled=egress_enabled,
    )
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_ONE_ID)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/demo/session")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    assert response.json()["external_model_egress_enabled"] is expected
