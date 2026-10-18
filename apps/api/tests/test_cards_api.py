from fastapi.testclient import TestClient
from finorch_api.infrastructure.database import get_db_session
from finorch_api.main import app
from finorch_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DEMO_USER_TWO_ID,
    DemoActor,
    get_current_demo_actor,
)

BOB_CARD_ID = "20000000-0000-4000-8000-000000000003"


def test_cards_api_returns_current_demo_user_page(seeded_database) -> None:
    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_ONE_ID)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/cards?limit=1&user_id=00000000-0000-4000-8000-000000000002",
                headers={"X-Request-ID": "cards-list-test-001"},
            )
            assert response.status_code == 200
            assert len(response.json()["items"]) == 1
            assert response.json()["next_cursor"]
            assert response.headers["X-Request-ID"] == "cards-list-test-001"

            cursor = response.json()["next_cursor"]
            next_page = client.get(f"/api/v1/cards?limit=1&cursor={cursor}")
            assert next_page.status_code == 200
            assert len(next_page.json()["items"]) == 1
            assert next_page.json()["next_cursor"] is None
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)


def test_cards_api_returns_not_found_for_foreign_card(seeded_database) -> None:
    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_ONE_ID)
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/cards/{BOB_CARD_ID}")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_cards_api_uses_server_context_for_second_demo_user(seeded_database) -> None:
    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_TWO_ID)
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/cards/{BOB_CARD_ID}")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)

    assert response.status_code == 200
    assert response.json()["id"] == BOB_CARD_ID


def test_invalid_cursor_has_standard_validation_error(seeded_database) -> None:
    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_ONE_ID)
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/cards?cursor=not-a-cursor")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
