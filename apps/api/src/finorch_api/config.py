from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINORCH_",
        env_file=".env",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    service_name: str = "finorch-api"
    service_version: str = "0.1.0"
    database_url: str = "sqlite:///./.data/finorch.db"
    demo_user_id: UUID = UUID("00000000-0000-4000-8000-000000000001")
    demo_now: datetime | None = None
    subscription_reminder_scheduler_enabled: bool = False
    subscription_reminder_scheduler_interval_seconds: int = Field(default=60, ge=10, le=3600)
    agent_provider: Literal["fake", "openai-compatible"] = "fake"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=120)
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    # Evaluation-only telemetry and listener identity. The provider only writes
    # sanitized token counts when this is configured in the test environment.
    eval_usage_file: Path | None = None
    eval_instance_id: str | None = Field(default=None, min_length=16, max_length=128)
    eval_max_completion_tokens: int | None = Field(default=None, gt=0, le=8192)
    eval_hard_budget_cny: float | None = Field(default=None, gt=0, le=120)
    eval_initial_cost_cny: float = Field(default=0, ge=0, le=120)


@lru_cache
def get_settings() -> Settings:
    return Settings()
