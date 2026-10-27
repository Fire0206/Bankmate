from pathlib import Path

import pytest
from finorch_api.config import Settings
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_env_example_loads_settings(monkeypatch, tmp_path) -> None:
    env_example = REPOSITORY_ROOT / ".env.example"
    env_contents = env_example.read_text(encoding="utf-8")
    env_lines = env_contents.splitlines()
    env_keys = [
        line.partition("=")[0]
        for line in env_lines
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    ]
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)

    expected_environment = "FINORCH_ENVIRONMENT=development"
    assert env_contents.count(expected_environment) == 1
    test_env_file = tmp_path / ".env"
    test_env_file.write_text(
        env_contents.replace(expected_environment, "FINORCH_ENVIRONMENT=test"),
        encoding="utf-8",
    )

    settings = Settings(_env_file=test_env_file)

    assert settings.environment == "test"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.service_name == "finorch-api"
    assert settings.service_version == "0.1.0"
    assert settings.database_url == "sqlite:///./.data/finorch.db"
    assert settings.llm_timeout_seconds == 60.0
    assert settings.llm_temperature == 0.2
    assert settings.llm_data_egress_enabled is False
    assert str(settings.demo_user_id) == "00000000-0000-4000-8000-000000000001"


def test_environment_variable_uses_pydantic_field_name(monkeypatch) -> None:
    monkeypatch.setenv("FINORCH_ENVIRONMENT", "test")

    settings = Settings(_env_file=None)

    assert settings.environment == "test"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_demo_api_accepts_loopback_hosts(host: str) -> None:
    settings = Settings(_env_file=None, api_host=host)

    assert settings.api_host == host.lower()


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.8", "api.example.com"])
def test_demo_api_rejects_non_loopback_hosts(host: str) -> None:
    with pytest.raises(ValidationError, match="loopback address"):
        Settings(_env_file=None, api_host=host)
