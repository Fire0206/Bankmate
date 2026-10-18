from functools import lru_cache
from typing import Literal
from uuid import UUID

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
