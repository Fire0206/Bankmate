import finorch_api.infrastructure.models as _models  # noqa: F401
from alembic import context
from finorch_api.config import get_settings
from finorch_api.infrastructure.database import Base, build_engine

config = context.config

target_metadata = Base.metadata


def _database_url() -> str:
    configured_url = config.attributes.get("database_url")
    return configured_url or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine(_database_url())
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
