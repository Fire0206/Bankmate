from fastapi.testclient import TestClient
from finorch_api.config import Settings
from finorch_api.main import app

client = TestClient(app)


def test_health_returns_api_process_status_and_request_id() -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "phase0-check-001"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "finorch-api",
        "version": "0.1.0",
    }
    assert response.headers["X-Request-ID"] == "phase0-check-001"


def test_unknown_route_uses_standard_error_envelope() -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["message"] == "Resource not found."
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_evaluation_instance_header_is_test_only(monkeypatch) -> None:
    import finorch_api.main as main_module

    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(_env_file=None, environment="test", eval_instance_id="phase2d-test-instance"),
    )
    response = TestClient(app).get("/api/v1/health")

    assert response.headers["X-FinOrch-Eval-Instance"] == "phase2d-test-instance"
    assert len(response.headers["X-FinOrch-Eval-Database"]) == 64

    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(_env_file=None, environment="development", eval_instance_id="not-for-development"),
    )
    response = TestClient(app).get("/api/v1/health")
    assert "X-FinOrch-Eval-Instance" not in response.headers
