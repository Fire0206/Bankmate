from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from bankmate_api.infrastructure.database import build_engine
from bankmate_api.seed_data import seed_demo_data
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class TestDatabase:
    engine: Engine
    session_factory: sessionmaker[Session]
    url: str


@pytest.fixture
def database(tmp_path: Path) -> TestDatabase:
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


@pytest.fixture
def seeded_database(database: TestDatabase) -> TestDatabase:
    with database.session_factory.begin() as session:
        seed_demo_data(session)
    return database
