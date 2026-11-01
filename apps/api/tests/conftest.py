from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from bankmate_api.config import get_settings
from bankmate_api.infrastructure.database import build_engine
from bankmate_api.seed_data import seed_demo_data

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class TestDatabase:
    engine: Engine
    session_factory: sessionmaker[Session]
    url: str


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestDatabase:
    monkeypatch.setenv("BANKMATE_DEMO_NOW", "2026-10-28T12:00:00+00:00")
    get_settings.cache_clear()
    database_path = tmp_path / "bankmate-test.sqlite3"
    database_url = URL.create("sqlite", database=str(database_path)).render_as_string(
        hide_password=False
    )
    engine = build_engine(database_url)

    alembic_config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    alembic_config.attributes["database_url"] = database_url
    command.upgrade(alembic_config, "head")

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield TestDatabase(engine=engine, session_factory=factory, url=database_url)
    engine.dispose()
    get_settings.cache_clear()


@pytest.fixture
def seeded_database(database: TestDatabase) -> TestDatabase:
    with database.session_factory.begin() as session:
        seed_demo_data(session)
    return database
