import argparse
import tempfile
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from finorch_api.config import get_settings
from finorch_api.infrastructure.database import get_session_factory
from finorch_api.infrastructure.models import Account, AuditEvent, Card, DemoUser
from finorch_api.seed_data import DATASET_VERSION, seed_demo_data


def validate_reset_target(*, environment: str, database_url: str, repository_root: Path) -> Path:
    if environment not in {"development", "test"}:
        raise ValueError("Database reset is allowed only in development or test environments.")

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or url.database in {None, "", ":memory:"}:
        raise ValueError("Reset requires a file-backed SQLite database.")

    database_path = Path(url.database)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    resolved_path = database_path.resolve()

    allowed_root = (
        (repository_root / ".data").resolve()
        if environment == "development"
        else Path(tempfile.gettempdir()).resolve()
    )
    if not resolved_path.is_relative_to(allowed_root) or resolved_path == allowed_root:
        raise ValueError(f"Reset target must be inside the allowed directory: {allowed_root}")
    if environment == "development" and resolved_path != (allowed_root / "finorch.db"):
        raise ValueError("Development reset is restricted to the repository .data/finorch.db file.")
    if environment == "test" and not (
        resolved_path.name.startswith("finorch-test") and resolved_path.suffix == ".sqlite3"
    ):
        raise ValueError("Test reset requires a temporary finorch-test*.sqlite3 file.")
    return resolved_path


def reset_demo_data(session: Session) -> None:
    """Clear the synthetic dataset and reseed it; the caller owns the transaction."""
    session.execute(delete(AuditEvent))
    session.execute(delete(Card))
    session.execute(delete(Account))
    session.execute(delete(DemoUser))
    seed_demo_data(session)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the local synthetic FinOrch dataset.")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm deleting and recreating the synthetic database contents.",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("--confirm is required; this replaces the database with synthetic seed data.")

    settings = get_settings()
    repository_root = Path(__file__).resolve().parents[4]
    target = validate_reset_target(
        environment=settings.environment,
        database_url=settings.database_url,
        repository_root=repository_root,
    )
    session_factory = get_session_factory(settings.database_url)
    with session_factory.begin() as session:
        reset_demo_data(session)
    print(f"Reset {target} to synthetic dataset {DATASET_VERSION}.")


if __name__ == "__main__":
    main()
