from finorch_api.config import get_settings
from finorch_api.infrastructure.database import get_session_factory
from finorch_api.seed_data import DATASET_VERSION, seed_demo_data


def main() -> None:
    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        raise SystemExit("Synthetic seed is allowed only in development or test environments.")
    session_factory = get_session_factory(settings.database_url)
    with session_factory.begin() as session:
        seed_demo_data(session)
    print(f"Seeded synthetic dataset {DATASET_VERSION}.")


if __name__ == "__main__":
    main()
