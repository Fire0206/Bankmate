from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from finorch_api.config import get_settings


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata for Alembic-managed tables."""


def build_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("Phase 1A supports SQLite database URLs only.")

    if url.database not in {None, "", ":memory:"}:
        database_path = Path(url.database)
        if not database_path.is_absolute():
            database_path = (Path.cwd() / database_path).resolve()
        database_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_constraints(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


@lru_cache(maxsize=8)
def get_engine(database_url: str) -> Engine:
    return build_engine(database_url)


@lru_cache(maxsize=8)
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(database_url),
        autoflush=False,
        expire_on_commit=False,
    )


def get_db_session() -> Iterator[Session]:
    """Own request-scoped Session creation/close; use cases own write transactions."""
    settings = get_settings()
    factory = get_session_factory(settings.database_url)
    with factory() as session:
        yield session
